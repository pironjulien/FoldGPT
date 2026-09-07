use std::io::{Read, Write};

fn main() -> std::io::Result<()> {
    if std::env::args().nth(1).as_deref() == Some("wait") {
        loop {
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
    }
    let mut input = Vec::new();
    std::io::stdin().read_to_end(&mut input)?;
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(&input)?;
    for index in 0..3000 {
        stdout.write_all(&[(index % 251) as u8; 257])?;
    }
    stdout.flush()?;
    let mut stderr = std::io::stderr().lock();
    for index in 0..1500 {
        stderr.write_all(&[(250 - index % 251) as u8; 257])?;
    }
    stderr.flush()?;
    std::process::exit(23);
}
