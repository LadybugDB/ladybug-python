from typing import TypeAlias

from ladybug import Connection, Database

ConnDB: TypeAlias = tuple[Connection, Database]
