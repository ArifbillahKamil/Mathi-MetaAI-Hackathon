"""Offline API boundary tests. No live key, network, or inference calls."""

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from app.core.independence import BlindRequest, Message, Method, RoutePlan, build_blind_requests
from app.llm.meta import ENDPOINT, MAX_RESPONSE_BYTES, MetaAPIError, MetaClient, MetaSettings, _NoRedirect


REQUEST = BlindRequest((Message("user", "Reply ready."),))
SETTINGS = MetaSettings("fixture-token")


def response(text="ready", *, finish="stop", usage=None):
    return {
        "id": "fixture-response", "model": "muse-spark-1.3",
        "choices": [{"finish_reason": finish, "message": {"content": text}}],
        "usage": usage if usage is not None else {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }


class MetaSettingsTests(unittest.TestCase):
    def load(self, text, environment=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text(text, encoding='utf-8')
            with patch.dict(os.environ, environment or {}, clear=True):
                return MetaSettings.from_dotenv(path)

    def test_loads_quoted_key_and_comment_without_exporting_it(self):
        settings = self.load('META_API_KEY="fixture-token" # private\nMETA_MODEL=muse-spark-1.2\n')
        self.assertEqual(settings.api_key, 'fixture-token')
        self.assertEqual(settings.model, 'muse-spark-1.2')

    def test_environment_overrides_dotenv(self):
        settings = self.load('META_API_KEY=file-token', {'META_API_KEY': 'environment-token'})
        self.assertEqual(settings.api_key, 'environment-token')

    def test_official_environment_name_is_also_accepted(self):
        settings = self.load('MODEL_API_KEY=official-alias')
        self.assertEqual(settings.api_key, 'official-alias')

    def test_missing_key_is_a_configuration_error(self):
        with self.assertRaises(ValueError):
            self.load('# no key')

    def test_secret_is_not_in_settings_repr(self):
        self.assertNotIn(SETTINGS.api_key, repr(SETTINGS))

    def test_unsupported_models_or_bad_timeouts_are_rejected(self):
        for model in ('unknown', 'muse-spark-1.3-contributor'):
            with self.subTest(model=model), self.assertRaises(ValueError):
                replace(SETTINGS, model=model)
        for timeout in (0, -1, float('nan'), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                replace(SETTINGS, timeout_seconds=timeout)

    def test_malformed_dotenv_error_does_not_echo_secret(self):
        with self.assertRaises(ValueError) as captured:
            self.load('META_API_KEY="unclosed-fixture-secret')
        self.assertNotIn('unclosed-fixture-secret', str(captured.exception))

    def test_unknown_dotenv_settings_are_not_evaluated(self):
        settings = self.load('IGNORED=$(arbitrary-command)\nMETA_API_KEY=fixture-token')
        self.assertEqual(settings.api_key, 'fixture-token')


class MetaClientTests(unittest.TestCase):
    def test_calls_have_exact_fresh_messages_and_no_shared_history(self):
        plan = RoutePlan(Method.SYMBOLIC_INTEGRATION, Method.NUMERICAL_QUADRATURE, 'Different methods.')
        a, b = build_blind_requests('Integrate x squared on [0, 1].', plan)
        client = MetaClient(SETTINGS)
        with patch.object(client, '_post', return_value=response()) as send:
            first = client.complete(a)
            second = client.complete(b)
        payloads = [json.loads(call.args[0]) for call in send.call_args_list]
        self.assertEqual(payloads[0]['messages'], a.to_dict()['messages'])
        self.assertEqual(payloads[1]['messages'], b.to_dict()['messages'])
        self.assertNotIn('previous_response_id', payloads[1])
        self.assertNotIn(SETTINGS.api_key, json.dumps(payloads))
        self.assertNotEqual(first.request_hash, second.request_hash)
        self.assertEqual(first.usage['total_tokens'], 6)

    def test_structured_output_uses_documented_strict_format(self):
        schema = {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code'], 'additionalProperties': False}
        client = MetaClient(SETTINGS)
        with patch.object(client, '_post', return_value=response('{"code":"print(1)"}')) as send:
            client.complete(REQUEST, schema=schema, max_completion_tokens=500)
        payload = json.loads(send.call_args.args[0])
        self.assertEqual(payload['response_format']['json_schema']['schema'], schema)
        self.assertTrue(payload['response_format']['json_schema']['strict'])
        self.assertEqual(payload['max_completion_tokens'], 500)
        self.assertNotIn('max_tokens', payload)

    def test_truncated_generation_is_not_returned_as_success(self):
        client = MetaClient(SETTINGS)
        with patch.object(client, '_post', return_value=response(finish='length')):
            with self.assertRaises(MetaAPIError) as captured:
                client.complete(REQUEST)
        self.assertEqual(captured.exception.code, 'INCOMPLETE_COMPLETION')

    def test_refusal_is_explicit(self):
        raw = response()
        raw['choices'][0]['message']['refusal'] = 'Cannot answer.'
        client = MetaClient(SETTINGS)
        with patch.object(client, '_post', return_value=raw), self.assertRaises(MetaAPIError) as captured:
            client.complete(REQUEST)
        self.assertEqual(captured.exception.code, 'MODEL_REFUSAL')

    def test_invalid_response_shapes_do_not_escape_as_success(self):
        for raw in ({}, {'choices': []}, response(text=None), response(text=' '), response(usage={'total_tokens': -1})):
            with self.subTest(raw=raw):
                client = MetaClient(SETTINGS)
                with patch.object(client, '_post', return_value=raw), self.assertRaises(MetaAPIError):
                    client.complete(REQUEST)

    def test_invalid_limits_or_history_are_rejected_before_transport(self):
        client = MetaClient(SETTINGS)
        with patch.object(client, '_post') as send:
            for tokens in (0, -1, True, 1.5):
                with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                    client.complete(REQUEST, max_completion_tokens=tokens)
            with self.assertRaises(ValueError):
                client.complete(BlindRequest((Message('assistant', 'Other route answer.'),)))
            with self.assertRaises(ValueError):
                client.complete(BlindRequest(()))
            with self.assertRaises(ValueError):
                client.complete(REQUEST, reasoning_effort='none')
        send.assert_not_called()

    def test_transport_uses_official_https_endpoint_and_bearer_header(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response()).encode()
        with patch('app.llm.meta.build_opener', return_value=opener):
            completion = MetaClient(SETTINGS).complete(REQUEST)
        sent = opener.open.call_args.args[0]
        self.assertEqual(sent.full_url, ENDPOINT)
        self.assertEqual(sent.get_header('Authorization'), 'Bearer fixture-token')
        self.assertEqual(completion.text, 'ready')

    def test_http_error_body_is_never_logged_or_retried(self):
        error = HTTPError(ENDPOINT, 401, 'Unauthorized', {}, io.BytesIO(b'echoed fixture-token'))
        opener = MagicMock()
        opener.open.side_effect = error
        with patch('app.llm.meta.build_opener', return_value=opener), self.assertRaises(MetaAPIError) as captured:
            MetaClient(SETTINGS).complete(REQUEST)
        self.assertEqual(captured.exception.status, 401)
        self.assertNotIn('fixture-token', str(captured.exception))
        self.assertEqual(opener.open.call_count, 1)

    def test_network_error_is_sanitized(self):
        opener = MagicMock()
        opener.open.side_effect = URLError('fixture-token inside untrusted error')
        with patch('app.llm.meta.build_opener', return_value=opener), self.assertRaises(MetaAPIError) as captured:
            MetaClient(SETTINGS).complete(REQUEST)
        self.assertEqual(captured.exception.code, 'META_CONNECTION_FAILED')
        self.assertNotIn('fixture-token', str(captured.exception))

    def test_redirect_cannot_forward_credentials(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_response_size_is_bounded(self):
        opener = MagicMock()
        reader = opener.open.return_value.__enter__.return_value.read
        reader.return_value = b'x' * (MAX_RESPONSE_BYTES + 1)
        with patch('app.llm.meta.build_opener', return_value=opener), self.assertRaises(MetaAPIError) as captured:
            MetaClient(SETTINGS).complete(REQUEST)
        self.assertEqual(captured.exception.code, 'API_RESPONSE_TOO_LARGE')
        reader.assert_called_once_with(MAX_RESPONSE_BYTES + 1)


if __name__ == '__main__':
    unittest.main()
