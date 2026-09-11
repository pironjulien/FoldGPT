# Security policy

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/pironjulien/FoldGPT/security/advisories/new) for security issues in FoldGPT. Do not post credentials, exploit payloads containing private data, or an unredacted device dump in a public issue.

A useful report includes the affected source revision, relevant device and Android versions, the violated boundary, reproducible steps, and the observed impact. Use synthetic accounts and files where possible. Share only the smallest evidence needed to reproduce the issue.

The current development branch is the supported security target. This is an alpha project with no response-time commitment or paid bug bounty. Fixes and affected versions will be described in a security advisory when appropriate.

## Security model

FoldGPT runs under an ordinary Android application UID. It does not require root or an unlocked bootloader. Android's application permissions and kernel remain responsible for the operating-system boundary.

The Linux compatibility environment is **not an equivalent replacement for desktop Linux sandboxing**. PRoot and the compatibility shim do not create Linux namespace isolation. The shim changes desktop sandbox-related behavior; native project authority checks do not establish containment for arbitrary plugins and tools.

The desktop package is obtained separately from OpenAI. FoldGPT applies compatibility adaptations, including a workspace integration tied to a recognized client version. Model and account requests still use online services; local command execution is not offline model inference.

## In scope

- Unauthorized access across intended workspace or Android permission boundaries.
- Runtime ownership, cleanup, or recovery that affects unrelated active work.
- Path traversal, unsafe extraction, package verification bypass, or untrusted update activation.
- Exposure of tokens, private project data, local control endpoints, or debugger interfaces.
- Command or argument handling that changes a requested operation's meaning.

Issues belonging solely to OpenAI, Android, Samsung, or another upstream component should also be reported through that vendor's security channel. Describe FoldGPT's integration impact when it is relevant.

## Evaluation guidance

Use a controlled test workspace with non-sensitive data while evaluating the alpha. Tools inherit the access available to their runtime; review optional Android permissions and plugin behavior before granting access. Do not treat a compatibility shim, a passed smoke test, or an intact boot state as proof of complete isolation.

The public source release excludes account material and proprietary runtime distributions. Please keep those exclusions intact in reports and pull requests.
