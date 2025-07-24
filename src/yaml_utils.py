"""
https://stackoverflow.com/questions/47614862/best-way-to-use-ruamel-yaml-to-dump-yaml-to-string-not-to-stream
https://stackoverflow.com/questions/71836675/force-pyyaml-to-write-multiline-string-literals-regardless-of-string-content
https://gist.github.com/alertedsnake/c521bc485b3805aa3839aef29e39f376
"""

from ruamel.yaml import YAML
from io import StringIO


def str_representer(dumper, data):
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml = YAML()
yaml.default_flow_style = False
yaml.indent(sequence=4, offset=2)
yaml.representer.add_representer(str, str_representer)


def dump_nice_yaml(data: dict) -> str:
    string_stream = StringIO()
    yaml.dump(data, string_stream)
    return string_stream.getvalue()


import yaml as _yaml

_yaml.dump_nice_yaml = dump_nice_yaml
