import Foundation
import ImageIO
import UIKit

/// The phone side of orch-relay. `URLSessionRelayClient` is the real thing, `MockRelay` the in-process fake.
protocol RelayAPI: Sendable {
    func pair(code: String, name: String) async throws -> PairResponse
    func registerPush(apnsToken: String, sandbox: Bool) async throws
    func workspaces() async throws -> [Workspace]
    func questions() async throws -> [Question]
    /// Newest first. `after` = the id of the last item of the previous page; `next` is the cursor for the page after this one.
    func messages(after: String?, limit: Int?) async throws -> ListResponse<PhoneMessage>
    func updates() async throws -> [TicketUpdate]
    func answer(_ request: AnswerRequest) async throws -> SendReceipt
    func send(_ request: SendRequest) async throws -> SendReceipt
    /// A phone upload (photo, file, voice memo), max 25 MB. Reads from disk so it can run in a background session.
    func uploadBlob(file: URL, contentType: String) async throws -> BlobUpload
    func transcribe(audio: Data, language: String?) async throws -> Transcript
    /// The text read aloud (`audio/mpeg`). Throws `.api(402 tts_cap_reached | 503 tts_off | 502 tts_failed | 404)`.
    func speech(messageId: String, lang: String?) async throws -> Data
    func settings() async throws -> PhoneSettings
    func updateSettings(_ patch: SettingsPatch) async throws -> PhoneSettings
    /// Redeem an invitation code (an already paired phone gets more workspaces).
    func redeem(code: String) async throws -> RedeemResponse
    func setMute(workspace: String, mute: Mute) async throws -> Workspace
    func removeWorkspace(_ id: String) async throws
    func signOut() async throws
    /// Raw bytes of a relay blob (images in a ticket chat). Only ever called with the paired credentials.
    func blob(id: String) async throws -> Data
}

extension RelayAPI {
    func messages() async throws -> [PhoneMessage] { try await messages(after: nil, limit: nil).items }
    /// A plain text: `ticket` nil = a new topic (see Phone app v3). Fresh client_id; the Outbox is what retries.
    func send(to: String, text: String, ticket: String?) async throws -> String {
        try await send(SendRequest(to: to, clientId: UUID().uuidString.lowercased(), text: text, ticket: ticket)).id
    }
    func answer(questionMessageId: String, answer: String) async throws -> String {
        try await self.answer(AnswerRequest(questionMessageId: questionMessageId, answer: answer, clientId: UUID().uuidString.lowercased())).id
    }
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
                         raw: (data: Data, type: String)? = nil, file: (url: URL, type: String)? = nil, accept: String = "application/json") async throws -> Data {
        var req = URLRequest(url: URL(string: path, relativeTo: base)!.absoluteURL)
        req.httpMethod = method
        req.setValue(accept, forHTTPHeaderField: "Accept")
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
        do {
            if let file {
                req.setValue(file.type, forHTTPHeaderField: "Content-Type"); req.timeoutInterval = 120
                (data, resp) = try await session.upload(for: req, fromFile: file.url)
            } else { (data, resp) = try await session.data(for: req) }
        }
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
    func messages(after: String?, limit: Int?) async throws -> ListResponse<PhoneMessage> {
        var q: [String] = []
        if let after { q.append("after=\(after.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? after)") }
        if let limit { q.append("limit=\(limit)") }
        let path = "/v1/phone/messages" + (q.isEmpty ? "" : "?" + q.joined(separator: "&"))
        return try JSONCoding.decoder.decode(ListResponse<PhoneMessage>.self, from: try await request("GET", path))
    }
    func updates() async throws -> [TicketUpdate] {
        try JSONCoding.decoder.decode(ListResponse<TicketUpdate>.self, from: try await request("GET", "/v1/phone/updates")).items
    }
    func answer(_ r: AnswerRequest) async throws -> SendReceipt {
        try JSONCoding.decoder.decode(SendReceipt.self, from: try await request("POST", "/v1/phone/answer", body: r))
    }
    func send(_ r: SendRequest) async throws -> SendReceipt {
        try JSONCoding.decoder.decode(SendReceipt.self, from: try await request("POST", "/v1/phone/send", body: r))
    }
    func uploadBlob(file: URL, contentType: String) async throws -> BlobUpload {
        try JSONCoding.decoder.decode(BlobUpload.self, from: try await request("POST", "/v1/phone/blobs", file: (file, contentType)))
    }
    func speech(messageId: String, lang: String?) async throws -> Data {
        guard BlobID.isValid(messageId) else { throw RelayError.api(status: 404, code: "not_found", message: "Nothing to read aloud.") }
        let q = lang.map { "?lang=\($0)" } ?? ""
        return try await request("GET", "/v1/phone/speech/\(messageId)\(q)", accept: "audio/mpeg")
    }
    func settings() async throws -> PhoneSettings {
        try JSONCoding.decoder.decode(PhoneSettings.self, from: try await request("GET", "/v1/phone/settings"))
    }
    func updateSettings(_ patch: SettingsPatch) async throws -> PhoneSettings {
        try JSONCoding.decoder.decode(PhoneSettings.self, from: try await request("PATCH", "/v1/phone/settings", body: patch))
    }
    func redeem(code: String) async throws -> RedeemResponse {
        struct Req: Encodable { let code: String }
        return try JSONCoding.decoder.decode(RedeemResponse.self, from: try await request("POST", "/v1/phone/invitations/redeem", body: Req(code: code)))
    }
    func setMute(workspace: String, mute: Mute) async throws -> Workspace {
        guard BlobID.isValid(workspace) else { throw RelayError.api(status: 404, code: "not_found", message: "Workspace not found.") }
        struct Req: Encodable {
            let mutedUntil: String?
            func encode(to e: Encoder) throws { var c = e.container(keyedBy: Key.self); try c.encode(mutedUntil, forKey: .mutedUntil) }   // always sent, null = unmute
            enum Key: String, CodingKey { case mutedUntil }
        }
        return try JSONCoding.decoder.decode(Workspace.self, from: try await request("PATCH", "/v1/phone/workspaces/\(workspace)", body: Req(mutedUntil: mute.wire)))
    }
    func removeWorkspace(_ id: String) async throws {
        guard BlobID.isValid(id) else { throw RelayError.api(status: 404, code: "not_found", message: "Workspace not found.") }
        _ = try await request("DELETE", "/v1/phone/workspaces/\(id)")
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
    static let maxBytes = 25 * 1024 * 1024
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
