# pyright: reportMissingTypeStubs=false
"""Deterministic crypto and C2PA fixtures generated only inside temporary directories."""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from pathlib import Path

import c2pa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
NOT_BEFORE = datetime(2026, 1, 1, tzinfo=UTC)
NOT_AFTER = datetime(2036, 1, 1, tzinfo=UTC)
C2PA_CLAIM_SIGNING_OID = ObjectIdentifier("1.3.6.1.4.1.62558.2.1")


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AegisQuant Test"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "FOR TESTING ONLY"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _certificate(
    *,
    subject: x509.Name,
    issuer: x509.Name,
    public_key: ec.EllipticCurvePublicKey,
    issuer_key: ec.EllipticCurvePrivateKey,
    issuer_public_key: ec.EllipticCurvePublicKey,
    serial: int,
    is_ca: bool,
    claim_signer: bool = False,
) -> x509.Certificate:
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(serial)
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=claim_signer,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=is_ca,
                crl_sign=is_ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_public_key),
            critical=False,
        )
    )
    if claim_signer:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([C2PA_CLAIM_SIGNING_OID]),
            critical=True,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def build_c2pa_assets(tmp_path: Path) -> tuple[Path, Path, str]:
    """Return a valid signed PNG, a byte-tampered copy, and its test root PEM."""

    root_key = ec.derive_private_key(11, ec.SECP256R1())
    root_name = _name("Root CA")
    root = _certificate(
        subject=root_name,
        issuer=root_name,
        public_key=root_key.public_key(),
        issuer_key=root_key,
        issuer_public_key=root_key.public_key(),
        serial=1001,
        is_ca=True,
    )
    intermediate_key = ec.derive_private_key(12, ec.SECP256R1())
    intermediate_name = _name("Intermediate CA")
    intermediate = _certificate(
        subject=intermediate_name,
        issuer=root_name,
        public_key=intermediate_key.public_key(),
        issuer_key=root_key,
        issuer_public_key=root_key.public_key(),
        serial=1002,
        is_ca=True,
    )
    leaf_key = ec.derive_private_key(13, ec.SECP256R1())
    leaf = _certificate(
        subject=_name("C2PA Signer"),
        issuer=intermediate_name,
        public_key=leaf_key.public_key(),
        issuer_key=intermediate_key,
        issuer_public_key=intermediate_key.public_key(),
        serial=1003,
        is_ca=False,
        claim_signer=True,
    )
    root_pem = root.public_bytes(serialization.Encoding.PEM).decode("ascii")
    certificate_chain = (
        leaf.public_bytes(serialization.Encoding.PEM)
        + intermediate.public_bytes(serialization.Encoding.PEM)
    ).decode("ascii")
    settings: dict[str, object] = {
        "version": 1,
        "builder": {"thumbnail": {"enabled": False}},
        "trust": {"user_anchors": root_pem},
        "verify": {
            "verify_after_reading": True,
            "verify_after_sign": True,
            "verify_trust": True,
            "verify_timestamp_trust": True,
            "ocsp_fetch": False,
            "remote_manifest_fetch": False,
        },
    }
    manifest = {
        "claim_generator_info": [{"name": "AegisQuant V5-P02", "version": "1.0.0"}],
        "claim_version": 2,
        "format": "image/png",
        "title": "V5-P02 C2PA fixture",
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": (
                                "http://c2pa.org/digitalsourcetype/trainedAlgorithmicMedia"
                            ),
                        }
                    ]
                },
            }
        ],
    }

    def sign(data: bytes) -> bytes:
        return leaf_key.sign(data, ec.ECDSA(hashes.SHA256()))

    output = io.BytesIO()
    with (
        c2pa.Context.from_dict(settings) as context,  # pyright: ignore[reportUnknownMemberType]
        c2pa.Signer.from_callback(
            sign,
            c2pa.C2paSigningAlg.ES256,
            certificate_chain,
            None,
        ) as signer,
        c2pa.Builder(manifest, context) as builder,
    ):
        builder.sign(signer, "image/png", io.BytesIO(PNG_BYTES), output)

    signed = tmp_path / "c2pa-valid.png"
    signed.write_bytes(output.getvalue())
    tampered_bytes = bytearray(output.getvalue())
    tampered_bytes[-20] ^= 1
    tampered = tmp_path / "c2pa-tampered.png"
    tampered.write_bytes(tampered_bytes)
    return signed, tampered, root_pem
