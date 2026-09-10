# Private host files protocol — contract for the Rust client

Schema: `foldgpt.host-files.v1`. The Python class is
`HostFileChannel` in `tools/executor/native_host_files_channel.py`.
It requires an existing `HostFileAuthority`, an already connected anonymous
AF_UNIX/SOCK_SEQPACKET socketpair, and actual trusted peer `(pid, uid, gid)`.
Enable SO_PASSCRED before handoff; each packet has exact kernel SCM_CREDENTIALS.
Unexpected ancillary data/SCM_RIGHTS or truncation closes the channel, with
received descriptors closed. No listener, pathname, model selector or policy.

Each packet is one UTF-8 JSON object, at most 65536 bytes. Duplicate keys,
non-finite numbers, unknown fields, wrong types and wrong sequence are fatal.
The Python side sends ASCII JSON and explicit actual SCM_CREDENTIALS. The Rust
side must check exact expected credentials on every packet too.

Ready, sent once by Python:

```json
{"type":"ready","schema":"foldgpt.host-files.v1","sessionId":"actual-owner-session","workspaceRoot":"file:///actual/owned/root","chunkBytes":32768,"maxDataBytes":16777216,"maxPacketBytes":65536,"operations":["readFile","writeFile","getMetadata","canonicalize","readDirectory","createDirectory"]}
```

One request at a time. IDs are exact integers starting at 1, incrementing after
each terminal response, with `1 <= id < 2^53`. Paths are canonical file URIs.
Exact request shapes:

```json
{"id":1,"op":"readFile","path":"file:///actual/owned/root/file"}
{"id":2,"op":"writeFile","path":"file:///actual/owned/root/file","bytes":3,"chunks":1}
{"id":3,"op":"getMetadata","path":"file:///actual/owned/root/file","followSymlinks":false}
{"id":4,"op":"canonicalize","path":"file:///actual/owned/root/file"}
{"id":5,"op":"readDirectory","path":"file:///actual/owned/root"}
{"id":6,"op":"createDirectory","path":"file:///actual/owned/root/dir","recursive":true}
```

`writeFile` header announces exact bounded byte count (0..16777216) and
`chunks = ceil(bytes / 32768)` (0..512). It is followed by exactly that many
client chunk packets, indices 0..chunks-1, exact shape:

```json
{"type":"chunk","id":2,"index":0,"dataBase64":"YWJj"}
{"type":"commit","id":2}
```

Each chunk contains canonical standard padded base64, decoding to exactly
32768 bytes except the final chunk which contains the exact remaining bytes.
An explicit commit packet is required even for a zero-byte write. Only after
the complete payload and commit framing are validated may the authority be
called. EOF, cancellation, wrong credentials or any malformed packet before
commit discards the payload without opening/mutating the destination. Commit
authorizes one actual write attempt; later cancellation/error is not rollback.
After commit, no further client packet until the terminal response.

`readFile` and `readDirectory` return zero or more server chunks with the same
chunk shape, followed by:

```json
{"type":"result","id":1,"result":{"bytes":3,"chunks":1}}
```

Read directory payload is UTF-8 JSON
`{"entries":[{"fileName":"file","isDirectory":false,"isFile":true}]}`.
Metadata result is the existing native typed metadata object, unchanged from
bootstrap. Canonicalize result is `{"path":"file:///actual/owned/root/file"}`
after actual native resolution. Write/create-directory success is:

```json
{"type":"result","id":2,"result":{}}
```

Native/authority refusal sends one terminal error and permits the next ID:

```json
{"type":"error","id":2,"error":{"code":-32004,"message":"actual native error"}}
```

NotFound (-32004) is retained only for real in-root absence. Admission denials
must never become absence. Protocol violations close without a success or a
retry. No operation is automatically retried; IDs cannot be replayed. Peer EOF
or task cancellation during an admitted native operation cancels it and waits
for actual helper reaping. Native owner remains responsible for global lease,
process cleanup and quarantine. The channel itself does not close that owner.

The client holds its request permit through full typed response validation.
Cancellation after admission closes the endpoint; cancellation while waiting
for another caller's permit does not close that other caller's operation.

Python implementation qualified on 2026-09-08: 30/30 actual nonroot tests
(15 authority + 15 transport), UID65534, snapshot
`/var/tmp/foldgpt-host-files-CVCFU6kF`. Complete 16MiB/512chunk read and write,
41 malformed-protocol refusals without mutation, actual foreign PID rejection,
descriptor closing, EOF/cancellation before commit, real helper cleanup after
commit and actual process lease/quarantine through the channel passed.
Client Rust integration remains separate; this is not an Android/UI success claim.
