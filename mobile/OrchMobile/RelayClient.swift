import Foundation
import ImageIO
import UIKit

/// The phone side of orch-relay. `URLSessionRelayClient` is the real thing, `MockRelay` the in-process fake.
protocol RelayAPI: Sendable {
    func pair(code: String, name: String) async throws -> PairResponse
    func registerPush(apnsToken: String, sandbox: Bool) async throws
    func workspaces() async throws -> [Workspace]
    func questions() async throws -> [Question]
    func messages() async throws -> [PhoneMessage]
    func updates() async throws -> [TicketUpdate]
    func answer(questionMessageId: String, answer: String) async throws -> String
    func send(to: String, text: String, ticket: String?) async throws -> String
    func transcribe(audio: Data, language: String?) async throws -> Transcript
    func signOut() async throws
    /// Raw bytes of a relay blob (images in a ticket chat). Only ever called with the paired credentials.
    func blob(id: String) async throws -> Data
}

enum RelayError: Error, Equatable, LocalizedError {
    case api(status: Int, code: String, message: String)
    case unauthorized
    case network(String)
    case badLink

    var errorDescription: String? {
        switch self {
        case .api(_, _, let m): return m
        case .unauthorized: return "This phone was signed out. Open the invitation you were sent to connect again."
        case .network(let m): return m
        case .badLink: return "That invitation link does not look right. Check you copied the whole link, or ask the person who invited you for a new one."
        }
    }
}

struct URLSessionRelayClient: RelayAPI {
    let base: URL
    let credentials: Credentials?
    let session: URLSession

    init(base: URL, credentials: Credentials? = nil, session: URLSession = .shared) {
        self.base = base; self.credentials = credentials; self.session = session
    }

    private struct ErrorBody: Decodable { let error: String?; let message: String? }

    private func request(_ method: String, _ path: String, body: (any Encodable)? = nil, auth: Bool = true,
                         raw: (data: Data, type: String)? = nil) async throws -> Data {
        var req = URLRequest(url: URL(string: path, relativeTo: base)!.absoluteURL)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if auth, let c = credentials {
            req.setValue(c.phoneId, forHTTPHeaderField: "X-Orch-Phone")
            req.setValue("Bearer \(c.token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONCoding.encoder.encode(AnyEncodable(body))
        }
        if let raw {
            req.setValue(raw.type, forHTTPHeaderField: "Content-Type")
            req.httpBody = raw.data
            req.timeoutInterval = 60
        }
        let data: Data, resp: URLResponse
        do { (data, resp) = try await session.data(for: req) }
        catch { throw RelayError.network("Could not reach your workspace server. Check your connection.") }
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if (200..<300).contains(status) { return data }
        if status == 401 && auth { throw RelayError.unauthorized }
        let e = try? JSONCoding.decoder.decode(ErrorBody.self, from: data)
        throw RelayError.api(status: status, code: e?.error ?? "error", message: e?.message ?? "Something went wrong (\(status)). Try again.")
    }

    func pair(code: String, name: String) async throws -> PairResponse {
        struct Req: Encodable { let code: String; let name: String }
        let d = try await request("POST", "/v1/phone/pair", body: Req(code: code, name: name), auth: false)
        return try JSONCoding.decoder.decode(PairResponse.self, from: d)
    }
    func registerPush(apnsToken: String, sandbox: Bool) async throws {
        struct Req: Encodable { let apnsToken: String; let sandbox: Bool }
        _ = try await request("POST", "/v1/phone/push", body: Req(apnsToken: apnsToken, sandbox: sandbox))
    }
    func workspaces() async throws -> [Workspace] {
        try JSONCoding.decoder.decode(ListResponse<Workspace>.self, from: try await request("GET", "/v1/phone/workspaces")).items
    }
    func questions() async throws -> [Question] {
        try JSONCoding.decoder.decode(ListResponse<Question>.self, from: try await request("GET", "/v1/phone/questions")).items
    }
    func messages() async throws -> [PhoneMessage] {
        try JSONCoding.decoder.decode(ListResponse<PhoneMessage>.self, from: try await request("GET", "/v1/phone/messages")).items
    }
    func updates() async throws -> [TicketUpdate] {
        try JSONCoding.decoder.decode(ListResponse<TicketUpdate>.self, from: try await request("GET", "/v1/phone/updates")).items
    }
    func answer(questionMessageId: String, answer: String) async throws -> String {
        struct Req: Encodable { let questionMessageId: String; let answer: String }
        let d = try await request("POST", "/v1/phone/answer", body: Req(questionMessageId: questionMessageId, answer: answer))
        return try JSONCoding.decoder.decode(IdResponse.self, from: d).id
    }
    func send(to: String, text: String, ticket: String?) async throws -> String {
        struct Req: Encodable { let to: String; let text: String; let ticket: String? }
        let d = try await request("POST", "/v1/phone/send", body: Req(to: to, text: text, ticket: ticket))
        return try JSONCoding.decoder.decode(IdResponse.self, from: d).id
    }
    func transcribe(audio: Data, language: String?) async throws -> Transcript {
        var path = "/v1/phone/transcribe"
        if let language { path += "?language=\(language)" }
        let d = try await request("POST", path, raw: (audio, "audio/m4a"))
        return try JSONCoding.decoder.decode(Transcript.self, from: d)
    }
    func signOut() async throws { _ = try await request("POST", "/v1/phone/signout") }
    func blob(id: String) async throws -> Data {
        guard BlobID.isValid(id) else { throw RelayError.api(status: 404, code: "not_found", message: "Image not found.") }
        guard let c = credentials else { throw RelayError.unauthorized }
        var req = URLRequest(url: URL(string: "/v1/phone/blobs/\(id)", relativeTo: base)!.absoluteURL)
        req.setValue(c.phoneId, forHTTPHeaderField: "X-Orch-Phone")
        req.setValue("Bearer \(c.token)", forHTTPHeaderField: "Authorization")
        let bytes: URLSession.AsyncBytes, resp: URLResponse
        do { (bytes, resp) = try await session.bytes(for: req) } catch { throw RelayError.network("Could not reach your workspace server. Check your connection.") }
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw RelayError.api(status: status, code: "error", message: "Image not available.") }
        if resp.expectedContentLength > Int64(BlobID.maxBytes) { throw RelayError.api(status: 413, code: "too_large", message: "Image too large.") }
        var d = Data()
        for try await b in bytes {
            d.append(b)
            if d.count > BlobID.maxBytes { throw RelayError.api(status: 413, code: "too_large", message: "Image too large.") }   // stop reading
        }
        return d
    }
}

private struct AnyEncodable: Encodable {
    let wrapped: any Encodable
    init(_ w: any Encodable) { wrapped = w }
    func encode(to encoder: Encoder) throws { try wrapped.encode(to: encoder) }
}

enum BlobID {
    static let maxBytes = 10_000_000
    static func isValid(_ id: String) -> Bool { id.range(of: "^[A-Za-z0-9_-]{1,64}$", options: .regularExpression) != nil }
}

/// Links from a workspace are only opened when they are plain web addresses (never tel:, file:, custom schemes).
enum SafeLink {
    static func url(_ raw: String?) -> URL? {
        guard let raw, let u = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = u.scheme?.lowercased(), scheme == "https" || scheme == "http", let host = u.host, !host.isEmpty else { return nil }
        return u
    }
    static func host(_ raw: String?) -> String? { url(raw)?.host }
}

/// Decodes an image as a bounded thumbnail (never the full-size bitmap).
enum Thumbnail {
    static func image(from data: Data, maxPixel: Int = 2048) -> UIImage? {
        guard let src = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary) else { return nil }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceThumbnailMaxPixelSize: maxPixel, kCGImageSourceShouldCacheImmediately: true]
        return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary).map { UIImage(cgImage: $0) }
    }
}
