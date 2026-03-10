from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from type_aliases import ConnDB


def test_to_json_string_param_roundtrip(conn_db_empty: ConnDB) -> None:
    """to_json() with a JSON string parameter should store the parsed object, not a string literal."""
    conn, _ = conn_db_empty
    conn.execute(
        """
        INSTALL json;
        LOAD json;
        CREATE NODE TABLE User (id SERIAL PRIMARY KEY, meta JSON);
        """
    )

    data = {
        "id": "http://localhost:8000/actors/testuser",
        "ap_data": {
            "id": "http://localhost:8000/actors/testuser",
            "type": "Person",
            "name": "",
            "summary": "",
            "username": "testuser",
            "inbox": "http://localhost:8000/actors/testuser/inbox",
            "outbox": "http://localhost:8000/actors/testuser/outbox",
            "public_key": {
                "id": "http://localhost:8000/actors/testuser#main-key",
                "owner": "http://localhost:8000/actors/testuser",
                "public_key_pem": (
                    "-----BEGIN PUBLIC KEY-----\n"
                    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAni2p5Ni2mVmHKFlOFA5w\n"
                    "zBLTZS3cEdiQ/IBqeSKYcKU4TFEhaFaVy3Be4pL+vFwX+iEXpvAznEhaC6oTU2zC\n"
                    "EaXFhmVInsZ3kzrz2vTeXsOIwJ4auR8fFziwewXYXUgT0/KmSlNaYMz1PbXxPS+P\n"
                    "DHL7E6ovJSau8Hj7UMDpF6W0Xty8PoU/Kw9Fyt3SXBHz6h5hvNXTiqS2HxWDbtz/\n"
                    "j5tZlpvxiZ/sFN2w/bsotlbe2QOF5HuLA/w7B3E1Tan8jLNO4qXEHffdUZEl92ad\n"
                    "dqnhsH9MJbRp6YfNnRMd1NaHu+rDUjTur34r5oVEz766oU/ZnGlGpJsvaQmUiMW8\n"
                    "XQIDAQAB\n"
                    "-----END PUBLIC KEY-----\n"
                ),
            },
            "manually_approve_followers": False,
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                {"manuallyApprovesFollowers": "as:manuallyApprovesFollowers"},
            ],
        },
        "is_local": True,
        "created_at": "2026-02-25T00:54:29.987623Z",
    }

    response = conn.execute(
        """
        CREATE (n:User {meta: to_json($meta)})
        RETURN n.id as id, cast(n.meta AS STRING) as meta;
        """,
        parameters={"meta": json.dumps(data)},
    )

    response_data = json.loads(response.rows_as_dict().get_all()[0]["meta"])
    assert response_data == data
