"""Firma SigV4: i due esempi ufficiali della documentazione AWS (Glacier) devono riprodursi esattamente."""
from datetime import datetime, timedelta, timezone

import pytest

from app.llm import sigv4

ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
URL = "https://glacier.us-east-1.amazonaws.com/-/vaults/examplevault"
GLACIER_VERSION = {"x-amz-glacier-version": "2012-06-01"}


def _sign(method, timestamp, body=b"", sign_content_sha256=True, url=URL, **extra):
    return sigv4.compute_signature(
        method=method, url=url, headers=GLACIER_VERSION, body=body, access_key=ACCESS_KEY, secret_key=SECRET_KEY,
        region="us-east-1", service="glacier", timestamp=timestamp, sign_content_sha256=sign_content_sha256, **extra)


def test_vector_1_put_vault_with_an_empty_body():
    got = _sign("PUT", datetime(2012, 5, 25, 0, 24, 53, tzinfo=timezone.utc), sign_content_sha256=False)
    assert got.canonical_request == "\n".join([
        "PUT",
        "/-/vaults/examplevault",
        "",
        "host:glacier.us-east-1.amazonaws.com",
        "x-amz-date:20120525T002453Z",
        "x-amz-glacier-version:2012-06-01",
        "",
        "host;x-amz-date;x-amz-glacier-version",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ])
    assert got.string_to_sign == "\n".join([
        "AWS4-HMAC-SHA256",
        "20120525T002453Z",
        "20120525/us-east-1/glacier/aws4_request",
        "5f1da1a2d0feb614dd03d71e87928b8e449ac87614479332aced3a701f916743",
    ])
    assert got.signature == "3ce5b2f2fffac9262b4da9256f8d086b4aaf42eba5f111c21681a65a127b7c2a"
    assert got.headers == {
        "Authorization": "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20120525/us-east-1/glacier/aws4_request, "
                         "SignedHeaders=host;x-amz-date;x-amz-glacier-version, "
                         "Signature=3ce5b2f2fffac9262b4da9256f8d086b4aaf42eba5f111c21681a65a127b7c2a",
        "x-amz-date": "20120525T002453Z",
    }


def test_vector_2_post_archive_with_a_body_and_the_payload_hash_header():
    payload_hash = "726e392cb4d09924dbad1cc0ba3b00c3643d03d14cb4b823e2f041cff612a628"
    # Il percorso dell'esempio ufficiale (upload di un archivio) è `.../archives`: senza, la firma non torna
    got = _sign("POST", datetime(2012, 5, 7, 0, 0, 0, tzinfo=timezone.utc), body=b"Welcome to Amazon Glacier.",
                url=URL + "/archives")
    assert got.canonical_request == "\n".join([
        "POST",
        "/-/vaults/examplevault/archives",
        "",
        "host:glacier.us-east-1.amazonaws.com",
        f"x-amz-content-sha256:{payload_hash}",
        "x-amz-date:20120507T000000Z",
        "x-amz-glacier-version:2012-06-01",
        "",
        "host;x-amz-content-sha256;x-amz-date;x-amz-glacier-version",
        payload_hash,
    ])
    assert got.signature == "b092397439375d59119072764a1e9a144677c43d9906fd98a5742c57a2855de6"
    assert got.headers["x-amz-content-sha256"] == payload_hash
    assert got.headers["x-amz-date"] == "20120507T000000Z"
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date;x-amz-glacier-version" in got.headers["Authorization"]


def test_two_more_official_vectors_from_the_sigv4_test_suite_and_the_iam_guide():
    key = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
    stamp = datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc)
    vanilla = sigv4.compute_signature(
        method="GET", url="https://example.amazonaws.com/", headers={}, body=b"", access_key="AKIDEXAMPLE",
        secret_key=key, region="us-east-1", service="service", timestamp=stamp, sign_content_sha256=False)
    assert vanilla.signature == "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    iam = sigv4.compute_signature(
        method="GET", url="https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, body=b"",
        access_key="AKIDEXAMPLE", secret_key=key, region="us-east-1", service="iam", timestamp=stamp,
        sign_content_sha256=False)
    assert iam.signature == "5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"


def test_a_session_token_is_signed_and_returned():
    stamp = datetime(2012, 5, 7, tzinfo=timezone.utc)
    plain, with_token = _sign("POST", stamp), _sign("POST", stamp, session_token="tok/en+1")
    assert with_token.headers["x-amz-security-token"] == "tok/en+1"
    assert "x-amz-security-token" not in plain.headers
    assert "x-amz-security-token:tok/en+1\n" in with_token.canonical_request
    assert "host;x-amz-content-sha256;x-amz-date;x-amz-glacier-version;x-amz-security-token" in with_token.headers["Authorization"]
    assert with_token.signature != plain.signature


def test_the_timestamp_is_converted_to_utc():
    local = datetime(2012, 5, 7, 2, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert _sign("POST", local).signature == _sign("POST", datetime(2012, 5, 7, tzinfo=timezone.utc)).signature


def test_query_parameters_are_sorted_and_encoded_and_the_path_is_encoded_twice():
    got = sigv4.compute_signature(
        method="GET", url="https://svc.us-east-1.amazonaws.com/a%3Ab/c?z=1&b=x y&a=&b=%2F", headers={}, body=b"",
        access_key=ACCESS_KEY, secret_key=SECRET_KEY, region="us-east-1", service="svc",
        timestamp=datetime(2012, 5, 7, tzinfo=timezone.utc))
    lines = got.canonical_request.split("\n")
    assert lines[1] == "/a%253Ab/c"
    assert lines[2] == "a=&b=%2F&b=x%20y&z=1"


def test_headers_values_are_trimmed_and_names_lowercased():
    got = sigv4.compute_signature(
        method="POST", url="https://svc.us-east-1.amazonaws.com/", headers={"Content-Type": "  application/json   x "},
        body=b"{}", access_key=ACCESS_KEY, secret_key=SECRET_KEY, region="us-east-1", service="svc",
        timestamp=datetime(2012, 5, 7, tzinfo=timezone.utc))
    assert "content-type:application/json x\n" in got.canonical_request


def test_sign_request_returns_only_the_headers():
    headers = sigv4.sign_request(
        method="POST", url=URL, headers={}, body=b"", access_key=ACCESS_KEY, secret_key=SECRET_KEY,
        region="us-east-1", service="glacier", timestamp=datetime(2012, 5, 7, tzinfo=timezone.utc))
    assert set(headers) == {"Authorization", "x-amz-date", "x-amz-content-sha256"}


@pytest.mark.parametrize("port_url, host", [("https://svc.example.com:8443/x", "svc.example.com:8443"),
                                             ("https://user:pw@svc.example.com/x", "svc.example.com")])
def test_the_host_header_comes_from_the_url(port_url, host):
    got = sigv4.compute_signature(
        method="GET", url=port_url, headers={}, body=b"", access_key=ACCESS_KEY, secret_key=SECRET_KEY,
        region="r", service="s", timestamp=datetime(2012, 5, 7, tzinfo=timezone.utc))
    assert f"host:{host}\n" in got.canonical_request
