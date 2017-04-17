from elasticsearch_dsl.serializer import AttrJSONSerializer
from nefertari import engine


def get_json_serializer():
    if engine.secondary is not None:
        SerializerBase = engine.primary.JSONEncoder
    else:
        SerializerBase = engine.common.JSONEncoderMixin

    class JSONSerializer(SerializerBase, AttrJSONSerializer):
        pass

    return JSONSerializer
