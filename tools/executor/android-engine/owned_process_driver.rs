// Appended inside the pinned codex-utils-pty process module by export_prototype.py.
// This is a process transport adapter, not a sandbox implementation.

/// Control of a real process owned by an external native runtime.
/// Success means the controller accepted the actual operation. Exit and stream
/// closure remain separate events; a failed request must not be acknowledged.
pub trait OwnedProcessController: Send + Sync {
    fn signal(&mut self, signal: ProcessSignal) -> io::Result<()>;
    fn request_terminate(&mut self) -> io::Result<()>;
    fn resize(&mut self, size: TerminalSize) -> anyhow::Result<()>;
}

/// An owned process with lossless bounded output channels.
///
/// The producer must apply backpressure through these channels and report any
/// transport failure separately. It closes each sender only after all bytes have
/// been forwarded. `exit_rx` is a process status, never a cleanup attestation.
/// The runtime must retain descendant ownership after this adapter is dropped.
pub struct OwnedProcessDriver {
    pub writer_tx: mpsc::Sender<Vec<u8>>,
    pub stdout_rx: mpsc::Receiver<Vec<u8>>,
    pub stderr_rx: mpsc::Receiver<Vec<u8>>,
    pub exit_rx: oneshot::Receiver<i32>,
    pub controller: Box<dyn OwnedProcessController>,
    /// Owns queued stdin writes. Dropping the final sender must close the actual
    /// child input after queued bytes are written, including for an empty input.
    pub writer_handle: Option<JoinHandle<()>>,
}

struct OwnedControllerTerminator {
    controller: Arc<StdMutex<Box<dyn OwnedProcessController>>>,
}

impl ChildTerminator for OwnedControllerTerminator {
    fn signal(&mut self, signal: ProcessSignal) -> io::Result<()> {
        self.controller
            .lock()
            .map_err(|_| io::Error::other("native process control lock poisoned"))?
            .signal(signal)
    }

    fn kill(&mut self) -> io::Result<()> {
        self.controller
            .lock()
            .map_err(|_| io::Error::other("native process control lock poisoned"))?
            .request_terminate()
    }
}

/// Adapt a native owned process without a broadcast hop or an output-copy task.
/// The existing upstream managers consume the same SpawnedProcess structure.
pub fn spawn_from_owned_driver(driver: OwnedProcessDriver) -> SpawnedProcess {
    let OwnedProcessDriver {
        writer_tx,
        stdout_rx,
        stderr_rx,
        exit_rx,
        controller,
        writer_handle,
    } = driver;
    let controller = Arc::new(StdMutex::new(controller));
    let resize_controller = Arc::clone(&controller);
    let exit_status = Arc::new(AtomicBool::new(false));
    let wait_exit_status = Arc::clone(&exit_status);
    let exit_code = Arc::new(StdMutex::new(None));
    let wait_exit_code = Arc::clone(&exit_code);
    let (exit_tx, exit_rx_out) = oneshot::channel();
    let wait_handle = tokio::spawn(async move {
        let code = exit_rx.await.unwrap_or(-1);
        wait_exit_status.store(true, std::sync::atomic::Ordering::SeqCst);
        if let Ok(mut guard) = wait_exit_code.lock() {
            *guard = Some(code);
        }
        let _ = exit_tx.send(code);
    });
    let session = ProcessHandle {
        writer_tx: StdMutex::new(Some(writer_tx)),
        killer: StdMutex::new(Some(Box::new(OwnedControllerTerminator { controller }))),
        reader_handle: StdMutex::new(None),
        reader_abort_handles: StdMutex::new(Vec::new()),
        writer_handle: StdMutex::new(writer_handle),
        wait_handle: StdMutex::new(Some(wait_handle)),
        exit_status,
        exit_code,
        _pty_handles: StdMutex::new(None),
        resizer: StdMutex::new(Some(Box::new(move |size| {
            resize_controller
                .lock()
                .map_err(|_| anyhow!("native resize control lock poisoned"))?
                .resize(size)
        }))),
        interrupt_preserves_control: true,
    };
    SpawnedProcess {
        session,
        stdout_rx,
        stderr_rx,
        exit_rx: exit_rx_out,
    }
}
