import CryptoKit
import Foundation

// Published pages for the artifact viewer (contracts/crypto.md section 1, publish-api.md "Public routes"). A published file lives
// at https://<host>/f/<id>#k=<key>; the server only has the encrypted blob (OPF1). The phone fetches the blob, decrypts it here and
// shows the result with the network blocked. Logic only: no views, no relay credentials (the blob route is public).

/// `https://<host>/f/<id>#k=<43 chars base64url>`.
struct PublishLink: Equatable, Sendable {
    let blobURL: URL
    let key: Data

    /// nil when the address is not a published file with a key (an app, a plain web page...).
    init?(_ url: URL) {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false), c.scheme == "https" || c.scheme == "http",
              let host = c.host else { return nil }
        let parts = c.path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        guard parts.count >= 2, parts[0] == "f", Self.validId(parts[1]) else { return nil }
        var frag = c.fragment ?? ""
        guard frag.hasPrefix("k=") else { return nil }
        frag.removeFirst(2)
        guard let key = Base64URL.decode(frag), key.count == 32 else { return nil }
        var b = URLComponents(); b.scheme = c.scheme; b.host = host; b.port = c.port; b.path = "/f/\(parts[1])/blob"
        guard let blob = b.url else { return nil }
        self.blobURL = blob; self.key = key
    }
    private static func validId(_ s: String) -> Bool {
        !s.isEmpty && s.count <= 64 && s.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }
    }
}

enum Base64URL {
    static func decode(_ s: String) -> Data? {
        var t = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while t.count % 4 != 0 { t += "=" }
        return Data(base64Encoded: t)
    }
}

/// What came out of an OPF1 blob.
struct PublishedFile: Equatable, Sendable {
    var name: String
    var type: String
    var note: String?
    var bytes: Data
    static let bundleType = "application/vnd.orch.bundle"
}

enum PublishError: Error, Equatable, LocalizedError {
    case broken, expired, unreachable
    var errorDescription: String? {
        switch self {
        case .broken: "This page could not be opened. The link may be wrong or the file broken."
        case .expired: "This page is no longer available."
        case .unreachable: "Can't reach the server. Check your connection, then try again."
        }
    }
}

enum OPF1 {
    private static let magic = Data("OPF1".utf8)

    /// Decrypts and validates a blob. Any failure is `.broken` ("wrong key or broken file"); the tag is checked before any byte is used.
    static func open(_ blob: Data, key: Data) throws -> PublishedFile {
        guard blob.count >= 32, blob.prefix(4) == magic, key.count == 32 else { throw PublishError.broken }
        let b = [UInt8](blob)
        let plain: Data
        do {
            let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: Data(b[4..<16])), ciphertext: Data(b[16..<(b.count - 16)]), tag: Data(b[(b.count - 16)...]))
            plain = try AES.GCM.open(box, using: SymmetricKey(data: key), authenticating: magic)
        } catch { throw PublishError.broken }
        guard plain.count >= 4 else { throw PublishError.broken }
        let p = [UInt8](plain)
        let n = Int(p[0]) << 24 | Int(p[1]) << 16 | Int(p[2]) << 8 | Int(p[3])
        guard n >= 1, n <= 65536, 4 + n <= p.count,
              let obj = try? JSONSerialization.jsonObject(with: Data(p[4..<(4 + n)])) as? [String: Any],
              let name = obj["name"] as? String, let type = obj["type"] as? String, let size = obj["size"] as? Int,
              size == p.count - 4 - n else { throw PublishError.broken }
        var note = (obj["note"] as? String).flatMap { $0.isEmpty ? nil : String($0.prefix(280)) }
        if note?.isEmpty == true { note = nil }
        return PublishedFile(name: name, type: type, note: note, bytes: Data(p[(4 + n)...]))
    }
}

/// A folder of pages (`application/vnd.orch.bundle`): the files by path and the page shown first.
struct PublishBundle: Equatable, Sendable {
    struct File: Equatable, Sendable { var path: String; var type: String; var data: Data }
    var entry: String
    var files: [File]

    func file(at path: String) -> File? { files.first { $0.path == path } }

    static func parse(_ data: Data) throws -> PublishBundle {
        let b = [UInt8](data)
        guard b.count >= 4 else { throw PublishError.broken }
        let m = Int(b[0]) << 24 | Int(b[1]) << 16 | Int(b[2]) << 8 | Int(b[3])
        guard m >= 1, m <= 1_048_576, 4 + m <= b.count,
              let idx = try? JSONSerialization.jsonObject(with: Data(b[4..<(4 + m)])) as? [String: Any],
              (idx["v"] as? Int) == 1, let entry = idx["entry"] as? String, let list = idx["files"] as? [[String: Any]],
              (1...2000).contains(list.count) else { throw PublishError.broken }
        var seen = Set<String>(), out: [File] = [], at = 4 + m
        var total = 0
        for f in list {
            guard let path = f["path"] as? String, let type = f["type"] as? String, let size = f["size"] as? Int, size >= 0,
                  validPath(path), seen.insert(path).inserted else { throw PublishError.broken }
            guard size <= (b.count - 4 - m) - total else { throw PublishError.broken }   // checked before adding: no overflow
            total += size
            out.append(File(path: path, type: type, data: Data(b[at..<(at + size)]))); at += size
        }
        let lower = entry.lowercased()
        guard total == b.count - 4 - m, seen.contains(entry), lower.hasSuffix(".html") || lower.hasSuffix(".htm") else { throw PublishError.broken }
        return PublishBundle(entry: entry, files: out)
    }

    private static func validPath(_ p: String) -> Bool {
        guard (1...255).contains(p.utf8.count), !p.hasPrefix("/"), !p.contains("\\"), !p.contains("\0") else { return false }
        return p.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }
}

/// What the viewer shows for a published address.
enum PublishContent: Equatable, Sendable {
    case page(html: String, name: String)            // one html file
    case bundle(PublishBundle, name: String)
    case file(PublishedFile)                         // pdf, image, anything else: the viewer decides by type

    static func from(_ f: PublishedFile) throws -> PublishContent {
        if f.type == PublishedFile.bundleType { return .bundle(try PublishBundle.parse(f.bytes), name: f.name) }
        if f.type.hasPrefix("text/html"), let s = String(data: f.bytes, encoding: .utf8) { return .page(html: s, name: f.name) }
        return .file(f)
    }
}

/// Fetches the encrypted blob (public route, no credentials) and opens it. The download is capped like the server's limit
/// (100 MiB of file + 64 KiB header + 36 bytes): a longer answer is refused up front or cut off while it streams.
struct PublishFetcher: Sendable {
    var session: URLSession = .shared
    static let maxBlobBytes = 100 * 1_048_576 + 65_536 + 36
    var maxBytes = PublishFetcher.maxBlobBytes

    func load(_ link: PublishLink) async throws -> PublishContent {
        var req = URLRequest(url: link.blobURL); req.timeoutInterval = 30
        let data = try await CappedDownload(maxBytes: maxBytes).run(req, configuration: session.configuration)
        return try PublishContent.from(try OPF1.open(data, key: link.key))
    }
}

/// One data task whose body is kept only while it stays under `maxBytes`.
final class CappedDownload: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let maxBytes: Int
    private var data = Data()
    private var failure: PublishError?
    private var status = 0
    private var continuation: CheckedContinuation<Data, Error>?
    init(maxBytes: Int) { self.maxBytes = maxBytes }

    func run(_ request: URLRequest, configuration: URLSessionConfiguration) async throws -> Data {
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let task = session.dataTask(with: request)
        nonisolated(unsafe) let cancellable = task
        // Closing the viewer cancels the awaiting task: the download stops with it instead of running on.
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { c in
                continuation = c
                task.resume()
                if Task.isCancelled { task.cancel() }
            }
        } onCancel: { cancellable.cancel() }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 410 || status == 404 { failure = .expired }
        else if status != 200 { failure = .unreachable }
        else if response.expectedContentLength > Int64(maxBytes) { failure = .broken }
        completionHandler(failure == nil ? .allow : .cancel)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive chunk: Data) {
        data.append(chunk)
        if data.count > maxBytes { failure = .broken; dataTask.cancel() }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let c = continuation else { return }
        continuation = nil
        if let failure { c.resume(throwing: failure) }
        else if (error as? URLError)?.code == .cancelled { c.resume(throwing: CancellationError()) }
        else if error != nil { c.resume(throwing: PublishError.unreachable) }
        else { c.resume(returning: data) }
    }
}
