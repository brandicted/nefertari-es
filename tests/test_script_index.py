from mock import patch, Mock, call

import nefertari_es
from nefertari_es.scripts.index import IndexCommand


@patch('nefertari_es.scripts.index.IndexCommand._prepare_env')
class TestIndexCommand(object):

    @patch('nefertari.engine')
    def test_nefertari_es_secondary_true(self, mock_eng, mock_prep):
        mock_eng.secondary = nefertari_es
        cmd = IndexCommand(None, None)
        assert cmd._nefertari_es_secondary()

    @patch('nefertari.engine')
    def test_nefertari_es_secondary_false(self, mock_eng, mock_prep):
        mock_eng.secondary = None
        cmd = IndexCommand(None, None)
        assert not cmd._nefertari_es_secondary()

    @patch('nefertari_es.scripts.index.IndexCommand._index_model')
    @patch('nefertari.engine')
    def test_run_not_secondary(self, mock_eng, mock_ind, mock_prep):
        mock_eng.secondary = None
        cmd = IndexCommand(None, None)
        cmd.logger = Mock()
        cmd.run()
        assert not mock_ind.called

    @patch('nefertari_es.scripts.index.IndexCommand._index_model')
    @patch('nefertari.engine')
    def test_run(self, mock_eng, mock_ind, mock_prep):
        mock_eng.secondary = nefertari_es
        cmd = IndexCommand(None, None)
        cmd.options = Mock(models='User,  Foo')
        cmd.logger = Mock()
        cmd.run()
        mock_ind.assert_has_calls([call('User'), call('Foo')])

    def test_index_docs(self, mock_prep):
        cmd = IndexCommand(None, None)
        cmd.logger = Mock()
        es_model = Mock()
        item = Mock()
        item.to_dict.return_value = {'foo': 1}
        cmd._index_docs(es_model, [item])
        item.to_dict.assert_called_once_with(_depth=0)
        es_model.assert_called_once_with(foo=1)
        es_model()._populate_meta_id.assert_called_once_with()
        es_model._index_many.assert_called_once_with([es_model()])

    @patch('nefertari_es.scripts.index.IndexCommand._index_docs')
    @patch('nefertari_es.scripts.index.engine')
    def test_index_model(self, mock_eng, mock_ind, mock_prep):
        es_model = Mock()
        es_model.pk_field.return_value = 'id'
        es_model.get_collection.return_value = []
        model = Mock(_secondary=es_model)
        item = Mock(id=1)
        model.get_collection.return_value = [item]
        mock_eng.get_document_cls.return_value = model
        cmd = IndexCommand(None, None)
        cmd.logger = Mock()
        cmd.options = Mock(force=False, params='foo=2')
        cmd._index_model('Foo')
        mock_eng.get_document_cls.assert_called_once_with('Foo')
        model.get_collection.assert_called_once_with(
            _query_secondary=False, foo='2')
        es_model.get_collection.assert_called_once_with(id=[1])
        assert not es_model._delete_many.called
        mock_ind.assert_called_once_with(es_model, [item])

    @patch('nefertari_es.scripts.index.IndexCommand._index_docs')
    @patch('nefertari_es.scripts.index.engine')
    def test_index_model_force(self, mock_eng, mock_ind, mock_prep):
        es_model = Mock()
        es_model.pk_field.return_value = 'id'
        es_item = Mock(id=1)
        es_model.get_collection.return_value = [es_item]
        model = Mock(_secondary=es_model)
        item = Mock(id=1)
        model.get_collection.return_value = [item]
        mock_eng.get_document_cls.return_value = model
        cmd = IndexCommand(None, None)
        cmd.logger = Mock()
        cmd.options = Mock(force=True, params='foo=2')
        cmd._index_model('Foo')
        mock_eng.get_document_cls.assert_called_once_with('Foo')
        model.get_collection.assert_called_once_with(
            _query_secondary=False, foo='2')
        es_model.get_collection.assert_called_once_with(id=[1])
        es_model._delete_many.assert_called_once_with([es_item])
        mock_ind.assert_called_once_with(es_model, [item])
