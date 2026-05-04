# mkfst examples

These are runnable demos. They are intentionally minimal and **not production-grade**.

## TLS material

`localhost.crt`, `localhost.key`, and `localhost.ca.crt` are throwaway, self-signed
development certificates regenerated for local testing. **Do not deploy these.**
They are useful only for the loopback demos in this directory.

If you need to issue your own:

```bash
python - <<'PY'
import trustme
ca = trustme.CA()
cert = ca.issue_cert("localhost", "127.0.0.1", "::1")
cert.private_key_pem.write_to_path("examples/localhost.key")
cert.cert_chain_pems[0].write_to_path("examples/localhost.crt")
ca.cert_pem.write_to_path("examples/localhost.ca.crt")
PY
```

## SECURITY NOTE

A previous version of this directory shipped a real Ed25519 private key
(`localhost.key`) on PyPI through the `mkfst` source distribution. **Treat that
historical key as compromised.** It has been replaced with the dev material
above. Anyone who pinned `mkfst <= 0.5.11` and reused that key in any context
should rotate.
