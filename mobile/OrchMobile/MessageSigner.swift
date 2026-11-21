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
}
