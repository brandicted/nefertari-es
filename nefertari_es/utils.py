from .fields import ReferenceField


relationship_fields = (
    ReferenceField,
)


def is_relationship_field(field, model_cls):
    return field in model_cls._relationships()


def get_relationship_cls(field, model_cls):
    field_obj = model_cls._doc_type.mapping[field]
    return field_obj._doc_class
