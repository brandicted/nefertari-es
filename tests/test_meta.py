import pytest
from mock import patch, call

from nefertari_es import meta, documents, fields


class TestMetaHelpers(object):

    @patch('nefertari_es.meta.Index')
    def test_create_index(self, mock_index):
        meta.create_index('index1', ['first', 'second'])
        mock_index.assert_called_once_with('index1')
        mock_index().doc_type.assert_has_calls([
            call('first'), call('second'),
        ], any_order=True)
        mock_index().create.assert_called_once_with()

    @patch('nefertari_es.meta.get_document_classes')
    @patch('nefertari_es.meta.Index')
    def test_test_create_index_no_classes(self, mock_index, mock_get):
        mock_get.return_value = {'foo': 'bar'}
        meta.create_index('index1')
        mock_index.assert_called_once_with('index1')
        mock_index().doc_type.assert_has_calls([
            call('bar')], any_order=True)
        mock_index().create.assert_called_once_with()
        mock_get.assert_called_once_with()


class TestDocumentRegistry(object):
    def test_get_document_cls_key_error(self):
        with pytest.raises(KeyError):
            meta.get_document_cls('MyItem1231')

    def test_get_document_cls(self):
        meta._document_registry = {'MyItem1231': 1}
        assert meta.get_document_cls('MyItem1231') == 1

    def test_get_document_classes(self):
        registry = meta.get_document_classes()
        assert registry == meta._document_registry
        assert registry is not meta._document_registry

    def test_registereddocumentmeta(self):
        from six import add_metaclass
        from elasticsearch_dsl.document import DocTypeMeta

        class MyMeta(meta.RegisteredDocMixin, DocTypeMeta):
            pass

        @add_metaclass(MyMeta)
        class MyItem123(object):
            pass

        assert meta._document_registry['MyItem123'] is MyItem123


class TestNonDocumentInheritanceMixin(object):

    def test_fields_added_to_mapping(self):
        class Mixin(object):
            username = fields.StringField(primary_key=True)

        class User(Mixin, documents.BaseDocument):
            password = fields.StringField()

        assert 'username' in User._doc_type.mapping
        assert isinstance(
            User._doc_type.mapping['username'],
            fields.StringField)
        assert 'password' in User._doc_type.mapping
        assert isinstance(
            User._doc_type.mapping['password'],
            fields.StringField)
        assert User.pk_field() == 'username'

        user = User(username='foo', password='bar')
        assert user.username == 'foo'
        assert user.password == 'bar'


class TestGenerateMetaMixin(object):

    def test_meta_generation(self):
        class FooBar(documents.BaseDocument):
            username = fields.StringField(primary_key=True)

        assert FooBar._doc_type.name == 'FooBar'


class TestBackrefGeneratingDocMixin(object):

    def test_backref_generation(self):
        class Tag(documents.BaseDocument):
            name = fields.StringField(primary_key=True)

        with pytest.raises(KeyError):
            Tag._doc_type.mapping['stories']

        class Story(documents.BaseDocument):
            name = fields.StringField(primary_key=True)
            tags = fields.Relationship(
                document='Tag', uselist=True,
                backref_name='stories')

        tag_stories = Tag._doc_type.mapping['stories']
        assert isinstance(tag_stories, fields.ReferenceField)
        assert tag_stories._back_populates == 'tags'
        assert tag_stories._is_backref
        assert tag_stories._doc_class is Story

        story_tags = Story._doc_type.mapping['tags']
        assert story_tags._back_populates == 'stories'
        assert not story_tags._is_backref
