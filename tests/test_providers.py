import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

from live_translator.ai.api_client import APIClient
from live_translator.ai.providers import create_adapter, ProviderError
from live_translator.ai.providers.base import NoRedirect
from live_translator.utils.settings import Settings, DEFAULT_SETTINGS


class ProviderTests(unittest.TestCase):
    def test_ollama_protocol(self):
        adapter = create_adapter("ollama", timeout=17)
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"response":" hello "}'
        with patch('live_translator.ai.providers.base.build_opener', return_value=opener):
            self.assertEqual(adapter.generate('local', 'translate'), 'hello')
        args, kwargs = opener.open.call_args
        self.assertEqual(kwargs['timeout'], 17)
        self.assertEqual(args[0].full_url, 'http://localhost:11434/api/generate')
        self.assertEqual(json.loads(args[0].data), {'model':'local','prompt':'translate','stream':False})

    def test_deepseek_key_and_protocol(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-secret'}):
            adapter = create_adapter('deepseek')
        self.assertEqual(adapter.api_key, 'test-secret')
        with patch.object(adapter, 'request', return_value={'choices':[{'message':{'content':' hi '}}]}) as request:
            self.assertEqual(adapter.generate('deepseek-v4-flash','hello'), 'hi')
        self.assertEqual(request.call_args.args[0], '/chat/completions')
        self.assertEqual(request.call_args.args[1]['thinking'], {'type':'disabled'})

    def test_missing_key_and_insecure_endpoint(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProviderError, 'DEEPSEEK_API_KEY'):
                create_adapter('deepseek').list_models()
        with self.assertRaises(ProviderError):
            create_adapter('deepseek', base_url='http://remote.example', api_key='secret')
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))

    def test_safe_http_errors_and_timeout(self):
        opener = MagicMock()
        for error, expected in ((HTTPError('url',401,'secret',{},None),'API key'),
                                (URLError('secret'),'Cannot reach'), (TimeoutError(),'timed out')):
            opener.open.side_effect = error
            with patch('live_translator.ai.providers.base.build_opener', return_value=opener):
                with self.assertRaisesRegex(ProviderError, expected) as caught:
                    create_adapter('ollama').list_models()
                self.assertNotIn('secret', str(caught.exception))

    def test_lmstudio_model_lifecycle(self):
        adapter = create_adapter('lmstudio', base_url='http://localhost:1234/v1')
        self.assertEqual(adapter.base_url, 'http://localhost:1234')
        response = {'models':[{'type':'llm','key':'model','loaded_instances':[{'id':'instance-1'}]},
                              {'type':'embedding','key':'embed'}]}
        with patch.object(adapter, 'request', return_value=response) as request:
            self.assertEqual(adapter.list_models(), ['model'])
            adapter.load('model')
            request.assert_called_with('/api/v1/models/load', {'model':'model'})
            adapter.unload('model')
            request.assert_called_with('/api/v1/models/unload', {'instance_id':'instance-1'})

    def test_lmstudio_server(self):
        adapter = create_adapter('lmstudio', base_url='http://localhost:2345')
        with patch('live_translator.ai.providers.lmstudio.shutil.which', return_value='/bin/lms'), patch('live_translator.ai.providers.lmstudio.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'running'
            self.assertEqual(adapter.server('start'), 'running')
            self.assertEqual(run.call_args.args[0], ['/bin/lms','server','start','--port','2345'])
        with self.assertRaises(ProviderError):
            create_adapter('lmstudio', base_url='http://remote.example').server('start')

    def test_disabled_makes_no_requests(self):
        with patch('live_translator.ai.api_client.create_adapter') as factory:
            self.assertIsNone(APIClient('none','').generate('hi'))
            factory.assert_not_called()

    def test_client_switch_and_connection_settings(self):
        settings = MagicMock()
        settings.get.return_value = {'api_key':'secret', 'timeout':99}
        with patch('live_translator.utils.settings.get_settings',return_value=settings), patch('live_translator.ai.api_client.create_adapter') as factory:
            factory.return_value.generate.return_value='translated'
            client=APIClient()
            client.set_settings(provider='deepseek',model='custom')
            self.assertEqual(client.generate('hello'),'translated')
            factory.assert_called_with('deepseek', api_key='secret',timeout=99)
            factory.return_value.generate.assert_called_with('custom','hello')
            client.set_settings(model='')
            self.assertIsNone(client.generate('hello'))
            self.assertIn('Select a model',client.last_error)

    def test_settings_isolation_and_private_save(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path,'home',return_value=Path(directory)):
            first=Settings()
            first.set('translation','model','custom')
            first.set('providers','deepseek',{'api_key':'secret'})
            second=Settings()
            self.assertEqual(second.get('translation','model'),DEFAULT_SETTINGS['translation']['model'])
            first.save()
            self.assertEqual(first.config_file.stat().st_mode & 0o777, 0o600)
            restored=Settings()
            self.assertEqual(restored.get('providers','deepseek'),{'api_key':'secret'})
            self.assertEqual(restored.get('translation','model'),'custom')
            copy=restored.get_all()
            copy['translation']['model']='mutated'
            self.assertEqual(restored.get('translation','model'),'custom')


if __name__ == '__main__':
    unittest.main()
