import CryptoKit
import Foundation

/// The phone signs what it sends in the one shared format (contracts/msgsig.md): it writes the message once as
/// JSON bytes, signs `"orch-sig-v1" 0x00 msg 0x00 <bytes>` and sends the envelope next to today's request.
/// A phone always signs `origin: person` and only to a workspace. The relay stores the signed id and body as they
/// are, so the workspace acts on exactly the bytes the person sent.
enum MessageSigner {
    /// One signed message before it is turned into bytes.
    struct Draft {
        var id: String = MessageSigner.newId()
        let from: String
        let to: String
        var type: String = "text"
        var createdMs: Int64 = MessageSigner.nowMs()
        let body: [String: Any]
        var ticket: String? = nil
        var replyTo: String? = nil
        var questionId: String? = nil
        var questionSha256: String? = nil
        var files: [File] = []
    }

    struct File: Equatable {
        let blobId: String
        let size: Int64
        let sha256: String
    }

    enum Problem: Error, Equatable { case noKey, badDraft(String) }

    static func nowMs() -> Int64 { Int64((Date().timeIntervalSince1970 * 1000).rounded(.down)) }

    /// `m_` + 16 lowercase letters and digits, the relay's message id form.
    static func newId() -> String {
        let alphabet = Array("abcdefghijklmnopqrstuvwxyz0123456789")
        var g = SystemRandomNumberGenerator()
        return "m_" + String((0..<16).map { _ in alphabet[Int(g.next(upperBound: UInt64(alphabet.count)))] })
    }

    /// The signed object, field for field as the contract names them.
    static func object(_ d: Draft) -> [String: Any] {
        var m: [String: Any] = ["v": 1, "id": d.id, "from": d.from, "to": d.to, "type": d.type,
                                "created_ms": d.createdMs, "origin": "person", "body": d.body]
        if let t = d.ticket { m["ticket"] = t }
        if let r = d.replyTo { m["reply_to"] = r }
        if let q = d.questionId { m["question_id"] = q }
        if let s = d.questionSha256 { m["question_sha256"] = s }
        if !d.files.isEmpty {
            m["files"] = d.files.map { ["blob_id": $0.blobId, "size": $0.size, "sha256": $0.sha256] as [String: Any] }
        }
        return m
    }

    /// Compact UTF-8 JSON with sorted keys. Swift strings hold no lone surrogates and JSONSerialization writes
    /// integers without fractions, so the bytes pass the strict reading rules; they are read back to be sure.
    static func bytes(_ d: Draft) throws -> [UInt8] {
        let data = try JSONSerialization.data(withJSONObject: object(d), options: [.sortedKeys, .withoutEscapingSlashes])
        let raw = [UInt8](data)
        do {
            try MessageSignature.checkFields(try MessageSignature.readStrictJSON(raw))
        } catch let r as MessageSignature.Refused {
            throw Problem.badDraft("\(r.code): \(r.why)")
        }
        return raw
    }

    /// The wire envelope `{sig_v, key_id, signed, sig}` for one draft.
    static func envelope(_ d: Draft, key: Curve25519.Signing.PrivateKey) throws -> [String: Any] {
        let signed = try bytes(d)
        let input = MessageSignature.signatureInput(purpose: "msg", signed: signed)
        let sig = try key.signature(for: Data(input))
        let pub = [UInt8](key.publicKey.rawRepresentation)
        return ["sig_v": 1, "key_id": MessageSignature.keyId(pub), "signed": MessageSignature.b64urlEncode(signed),
                "sig": MessageSignature.b64urlEncode([UInt8](sig))]
    }

    /// Same, with this phone's own key.
    static func envelope(_ d: Draft) throws -> [String: Any] {
        guard let key = PhoneKey.current() else { throw Problem.noKey }
        return try envelope(d, key: key)
    }

    /// SHA-256 hex of the question's signed bytes, which a signed answer names (`question_sha256`).
    static func questionSha256(envelope: Any?) -> String? {
        guard let e = try? MessageSignature.readEnvelope(envelope) else { return nil }
        return SHA256.hash(data: Data(e.signed)).map { String(format: "%02x", $0) }.joined()
    }

    /// Body keys the relay copies from a send request into the message it stores (relay `phone.rs` send).
    static let sendBodyKeys = ["client_id", "general", "text", "attachments", "voice", "location", "feedback", "team"]

    /// Sign a send request: the signed body is built from the request exactly as the relay builds its body, so the
    /// workspace gets the person's own words. `fileFacts` gives size and SHA-256 of each named blob (from the
    /// phone's local copy). Returns nil when the request cannot be signed in v1 (a number with a fraction, such as
    /// a location or a recording length); it then goes as before, unsigned.
    static func sign(_ r: SendRequest, phoneId: String, key: Curve25519.Signing.PrivateKey,
                     fileFacts: (String) -> (size: Int64, sha256: String)?) -> SignedEnvelope? {
        var plain = r
        plain.envelope = nil
        guard let data = try? JSONCoding.encoder.encode(plain),
              let all = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var body: [String: Any] = [:]
        for k in sendBodyKeys { if let v = all[k], !(v is NSNull) { body[k] = v } }
        var blobs: [String] = (r.attachments ?? []).map(\.blobId)
        if let v = r.voice { blobs.append(v.blobId) }
        blobs += (r.feedback?.pins ?? []).compactMap(\.voiceBlobId)
        var files: [File] = []
        for b in blobs {
            guard let f = fileFacts(b) else { return nil }
            files.append(File(blobId: b, size: f.size, sha256: f.sha256))
        }
        let d = Draft(from: phoneId, to: r.to, body: body, ticket: r.ticket, replyTo: r.replyTo, files: files)
        guard let e = try? envelope(d, key: key) else { return nil }
        return SignedEnvelope(sigV: 1, keyId: e["key_id"] as! String, signed: e["signed"] as! String, sig: e["sig"] as! String)
    }

    /// Sign an answer to a signed question (relay-api.md `/v1/phone/answer`, ORCH-1204 c9). The signed body is the
    /// body the relay builds: question_id, answer, answered_by `human:<phone id>`, client_id and the verdict as sent.
    /// The signed answer names the question by `question_id` and `question_sha256`, and lists every blob the verdict
    /// names. Nil when it cannot be signed in v1 (an unreadable question envelope, a number with a fraction, a file
    /// without a local copy, a blob named twice); the answer then goes as before, unsigned.
    static func signAnswer(_ r: AnswerRequest, to workspace: String, ticket: String?, questionId: String,
                           questionEnvelope: [String: Any], phoneId: String, key: Curve25519.Signing.PrivateKey,
                           fileFacts: (String) -> (size: Int64, sha256: String)?) -> SignedEnvelope? {
        guard let sha = questionSha256(envelope: questionEnvelope) else { return nil }
        var plain = r
        plain.envelope = nil
        guard let data = try? JSONCoding.encoder.encode(plain),
              let all = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var body: [String: Any] = ["question_id": questionId, "answer": r.answer, "answered_by": "human:\(phoneId)",
                                   "client_id": r.clientId]
        var blobs: [String] = []
        if let v = all["verdict"] as? [String: Any] {
            body["verdict"] = v
            let note = v["note"] as? [String: Any]
            for vo in ((note?["words"] as? [String: Any])?["voice"] as? [[String: Any]]) ?? [] {
                guard let b = vo["blob_id"] as? String else { return nil }
                blobs.append(b)
            }
            for f in (note?["files"] as? [[String: Any]]) ?? [] {
                guard let b = f["blob_id"] as? String else { return nil }
                blobs.append(b)
            }
        }
        guard Set(blobs).count == blobs.count else { return nil }
        var files: [File] = []
        for b in blobs {
            guard let f = fileFacts(b) else { return nil }
            files.append(File(blobId: b, size: f.size, sha256: f.sha256))
        }
        let d = Draft(from: phoneId, to: workspace, type: "answer", body: body, ticket: ticket,
                      replyTo: r.questionMessageId, questionId: questionId, questionSha256: sha, files: files)
        guard let e = try? envelope(d, key: key) else { return nil }
        return SignedEnvelope(sigV: 1, keyId: e["key_id"] as! String, signed: e["signed"] as! String, sig: e["sig"] as! String)
    }

    /// Size and SHA-256 hex of a local file.
    static func facts(of url: URL) -> (size: Int64, sha256: String)? {
        guard let data = try? Data(contentsOf: url, options: .mappedIfSafe) else { return nil }
        return (Int64(data.count), SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined())
    }
}
