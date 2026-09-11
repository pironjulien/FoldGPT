# Desktop compatibility shim

These sources belong to the desktop compatibility layer, separate from the native executor.

| File | Purpose |
| --- | --- |
| `fake_userns.c` | Historical namespace compatibility shim used by the desktop client |
| `audit-shim.c` | Diagnostic comparing libc and direct syscalls to reveal the shim’s actual boundaries |
| `test_userns.c` | Manual diagnostic for the shim’s namespace-related return values |

The shim emulates selected namespace operations; it does **not** implement Linux namespace isolation. Keep its source and diagnostic evidence available when reviewing a runtime that contains the corresponding library. These programs are not the automated regression suite and are not run by public CI.

See the [historical native-startup audit](../../docs/history/native-startup-2026-09-05.md), [security policy](../../SECURITY.md) and [maintained tests](../../tests/README.md).
