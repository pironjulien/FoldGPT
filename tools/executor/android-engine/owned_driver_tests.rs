use codex_utils_pty::{
    OwnedProcessController, OwnedProcessDriver, ProcessSignal, SpawnedProcess, TerminalSize,
    spawn_from_owned_driver,
};
use std::io::{self, Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};

struct PcChild(Arc<Mutex<Child>>);
impl OwnedProcessController for PcChild {
    fn signal(&mut self, _: ProcessSignal) -> io::Result<()> {
        #[cfg(unix)]
        {
            let pid = self.0.lock().unwrap().id();
            if unsafe { libc::kill(pid as i32, libc::SIGINT) } == -1 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        }
        #[cfg(not(unix))]
        {
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "PC pipe fixture has no console",
            ))
        }
    }
    fn request_terminate(&mut self) -> io::Result<()> {
        self.0.lock().unwrap().kill()
    }
    fn resize(&mut self, _: TerminalSize) -> anyhow::Result<()> {
        Err(io::Error::new(io::ErrorKind::Unsupported, "real pipe fixture has no PTY").into())
    }
}

fn read_output(mut pipe: impl Read + Send + 'static, sender: mpsc::Sender<Vec<u8>>) {
    tokio::task::spawn_blocking(move || {
        let mut buffer = [0; 257];
        loop {
            let size = pipe.read(&mut buffer).expect("read real child pipe");
            if size == 0 {
                break;
            }
            if sender.blocking_send(buffer[..size].to_vec()).is_err() {
                break;
            }
        }
    });
}

fn real_child(mode: &str) -> (SpawnedProcess, Arc<Mutex<Child>>) {
    let mut command = Command::new(env!("CARGO_BIN_EXE_owned_driver_fixture"));
    command
        .arg(mode)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().expect("launch actual fixture binary");
    let mut input = child.stdin.take().unwrap();
    let (writer_tx, mut writer_rx) = mpsc::channel::<Vec<u8>>(1);
    let writer_handle = tokio::task::spawn_blocking(move || {
        while let Some(chunk) = writer_rx.blocking_recv() {
            if input.write_all(&chunk).is_err() {
                break;
            }
        }
        drop(input);
    });
    let (stdout_tx, stdout_rx) = mpsc::channel(1);
    let (stderr_tx, stderr_rx) = mpsc::channel(1);
    read_output(child.stdout.take().unwrap(), stdout_tx);
    read_output(child.stderr.take().unwrap(), stderr_tx);
    let child = Arc::new(Mutex::new(child));
    let waiter = Arc::clone(&child);
    let (exit_tx, exit_rx) = oneshot::channel();
    tokio::spawn(async move {
        loop {
            let status = waiter
                .lock()
                .unwrap()
                .try_wait()
                .expect("wait actual child");
            if let Some(status) = status {
                let _ = exit_tx.send(status.code().unwrap_or(-1));
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    });
    (
        spawn_from_owned_driver(OwnedProcessDriver {
            writer_tx,
            stdout_rx,
            stderr_rx,
            exit_rx,
            controller: Box::new(PcChild(Arc::clone(&child))),
            writer_handle: Some(writer_handle),
        }),
        child,
    )
}

async fn drain(mut receiver: mpsc::Receiver<Vec<u8>>) -> Vec<u8> {
    let mut bytes = Vec::new();
    while let Some(chunk) = receiver.recv().await {
        bytes.extend(chunk);
    }
    bytes
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn owned_driver_preserves_real_binary_streams_and_stdin_eof() {
    let (process, child) = real_child("bulk");
    let input = vec![0, 255, 13, 10, 0, 128];
    let writer = process.session.writer_sender();
    writer.send(input.clone()).await.unwrap();
    drop(writer);
    process.session.close_stdin();
    // The one-chunk channels deliberately fill while the consumer is absent.
    tokio::time::sleep(Duration::from_millis(50)).await;
    let (stdout, stderr, code) = tokio::time::timeout(Duration::from_secs(15), async {
        tokio::join!(
            drain(process.stdout_rx),
            drain(process.stderr_rx),
            process.exit_rx
        )
    })
    .await
    .expect("actual process and both streams finish");
    let mut expected_stdout = input;
    for index in 0..3000 {
        expected_stdout.extend([(index % 251) as u8; 257]);
    }
    let mut expected_stderr = Vec::new();
    for index in 0..1500 {
        expected_stderr.extend([(250 - index % 251) as u8; 257]);
    }
    assert_eq!(stdout, expected_stdout);
    assert_eq!(stderr, expected_stderr);
    assert_eq!(code.unwrap(), 23);
    assert!(child.lock().unwrap().try_wait().unwrap().is_some());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn owned_driver_forwards_controls_and_terminates_real_child() {
    let (process, child) = real_child("wait");
    assert!(
        process
            .session
            .resize(TerminalSize { rows: 24, cols: 80 })
            .is_err()
    );
    #[cfg(not(unix))]
    assert_eq!(
        process
            .session
            .signal(ProcessSignal::Interrupt)
            .unwrap_err()
            .kind(),
        io::ErrorKind::Unsupported
    );
    process.session.try_request_terminate().unwrap();
    let code = tokio::time::timeout(Duration::from_secs(5), process.exit_rx)
        .await
        .unwrap()
        .unwrap();
    assert_ne!(code, 0);
    assert!(child.lock().unwrap().try_wait().unwrap().is_some());
}
