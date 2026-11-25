//! {{name}}: a small Rust app for orch publish (docker stack, store {{store}}).
//! The host sets HOST, PORT, BASE_PATH, DATA_DIR and STORE. Requests arrive without the BASE_PATH prefix.

use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::thread;

fn visits() -> Option<u64> {
    if env::var("STORE").unwrap_or_default() == "none" {
        return None;
    }
    let file: PathBuf = [env::var("DATA_DIR").unwrap_or_else(|_| ".data".into()), "visits.txt".into()]
        .iter()
        .collect();
    let n = fs::read_to_string(&file).ok().and_then(|s| s.trim().parse().ok()).unwrap_or(0) + 1;
    fs::create_dir_all(file.parent()?).ok()?;
    fs::write(&file, n.to_string()).ok()?;
    Some(n)
}

fn answer(path: &str) -> (&'static str, &'static str, String) {
    match path {
        "/health" => ("200 OK", "text/plain", "ok".into()),
        "/" | "/index.html" => {
            let seen = visits().map(|n| format!("<p>Visits: {n}</p>")).unwrap_or_default();
            (
                "200 OK",
                "text/html; charset=utf-8",
                format!(
                    "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">\
                     <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\
                     <title>{{name}}</title><main><h1>{{name}}</h1>{seen}</main></html>"
                ),
            )
        }
        _ => ("404 Not Found", "text/plain", "not found".into()),
    }
}

fn handle(mut stream: TcpStream) {
    let mut buf = [0u8; 4096];
    let n = stream.read(&mut buf).unwrap_or(0);
    let head = String::from_utf8_lossy(&buf[..n]);
    let mut parts = head.split_whitespace();
    let (method, target) = (parts.next().unwrap_or(""), parts.next().unwrap_or("/"));
    let path = target.split('?').next().unwrap_or("/");
    let (status, ctype, body) = if method == "GET" || method == "HEAD" {
        answer(path)
    } else {
        ("405 Method Not Allowed", "text/plain", "method not allowed".into())
    };
    let body = if method == "HEAD" { String::new() } else { body };
    let _ = write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
}

fn main() {
    if env::args().any(|a| a == "--check") {
        assert_eq!(answer("/health").2, "ok");
        assert_eq!(answer("/nope").0, "404 Not Found");
        return;
    }
    let host = env::var("HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port = env::var("PORT").unwrap_or_else(|_| "8000".into());
    let listener = TcpListener::bind(format!("{host}:{port}")).expect("cannot listen on $HOST:$PORT");
    for stream in listener.incoming().flatten() {
        thread::spawn(move || handle(stream));
    }
}
