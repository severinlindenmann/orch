import CryptoKit
import Foundation

/// Signed messages v1 (contracts/relay-api.md "Signed messages", vectors/signing-v1.json).
/// Pure: the format, strict reading, key ids, fingerprints and the receiver's checks. The trust store, seen ids
/// and held messages come in as arguments (wired up in a later ticket). CryptoKit signatures are randomized, so
/// the phone checks verification only; it never needs to reproduce a vector signature.
enum MessageSignature {
    static let tag = Array("orch-sig-v1".utf8)
    static let purposes = ["msg", "report", "key-rotate", "key-withdraw"]
    static let maxSignedBytes = 262_144
    static let maxDepth = 32
    static let maxSafeInt: Int64 = (1 << 53) - 1
    static let futureSkewMs: Int64 = 5 * 60 * 1000
    static let maxExpiryMs: Int64 = 60 * 60 * 1000
    static let maxAgeMs: Int64 = 30 * 24 * 60 * 60 * 1000
    static let maxFileSize: Int64 = 100 * 1024 * 1024
    static let maxFiles = 20
    static let types = ["text", "file", "question", "answer", "delegate", "start", "allow"]
    static let expiring = ["allow", "delegate", "start"]
    static let fileTypes = ["text", "file", "question", "answer"]
    static let groupTypes = ["text", "file", "question"]

    /// A refusal; `code` is the contract's code.
    struct Refused: Error, Equatable {
        let code: String
        let why: String
        init(_ code: String, _ why: String = "") { self.code = code; self.why = why }
    }

    /// A value of the signed JSON: integers only (no fractions), as the strict rules say.
    indirect enum JSON: Equatable {
        case object([String: JSON])
        case array([JSON])
        case string(String)
        case int(Int64)
        case bool(Bool)
        case null

        var string: String? { if case let .string(s) = self { return s }; return nil }
        var int: Int64? { if case let .int(n) = self { return n }; return nil }
        var object: [String: JSON]? { if case let .object(o) = self { return o }; return nil }
        var array: [JSON]? { if case let .array(a) = self { return a }; return nil }
    }

    // MARK: keys

    static func keyHash(_ pub: [UInt8]) -> [UInt8] {
        Array(SHA256.hash(data: Array("ed25519".utf8) + pub))
    }

    static func keyId(_ pub: [UInt8]) -> String {
        keyHash(pub).prefix(8).map { String(format: "%02x", $0) }.joined()
    }

    static func fingerprint(_ pub: [UInt8]) -> String {
        let alphabet = Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
        var out: [Character] = []
        var acc: UInt32 = 0
        var bits = 0
        for b in keyHash(pub).prefix(20) {
            acc = (acc << 8) | UInt32(b)
            bits += 8
            while bits >= 5 {
                bits -= 5
                out.append(alphabet[Int((acc >> UInt32(bits)) & 31)])
            }
            acc &= (1 << UInt32(bits)) - 1
        }
        return stride(from: 0, to: 32, by: 4).map { String(out[$0..<$0 + 4]) }.joined(separator: " ")
    }

    private static let smallOrderY: [[UInt8]] = [
        [UInt8](repeating: 0, count: 32),
        [1] + [UInt8](repeating: 0, count: 31),
        [0xec] + [UInt8](repeating: 0xff, count: 30) + [0x7f],
        hexBytes("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"),
        hexBytes("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"),
    ]

    static func hexBytes(_ s: String) -> [UInt8] {
        var out: [UInt8] = []
        var it = s.makeIterator()
        while let a = it.next(), let b = it.next() {
            guard let v = UInt8(String([a, b]), radix: 16) else { return [] }
            out.append(v)
        }
        return out
    }

    /// 32 bytes, canonical y (< p), not a small-order point (whatever the sign bit). Same rule as the workspace.
    static func publicKeyOK(_ pub: [UInt8]) -> Bool {
        guard pub.count == 32 else { return false }
        var y = pub
        y[31] &= 0x7f
        var p = [UInt8](repeating: 0xff, count: 32)
        p[0] = 0xed
        p[31] = 0x7f
        var less = false
        for i in stride(from: 31, through: 0, by: -1) where y[i] != p[i] {
            less = y[i] < p[i]
            break
        }
        return less && !smallOrderY.contains(y)
    }

    static func verifyRaw(pub: [UInt8], data: [UInt8], sig: [UInt8]) -> Bool {
        guard publicKeyOK(pub), sig.count == 64,
              let key = try? Curve25519.Signing.PublicKey(rawRepresentation: pub) else { return false }
        return key.isValidSignature(Data(sig), for: Data(data))
    }

    static func signatureInput(purpose: String, signed: [UInt8]) -> [UInt8] {
        precondition(purposes.contains(purpose), "unknown purpose")
        return tag + [0] + Array(purpose.utf8) + [0] + signed
    }

    // MARK: base64url, strict

    static func b64urlEncode(_ b: [UInt8]) -> String {
        Data(b).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func b64urlDecodeStrict(_ s: String) -> [UInt8]? {
        let ok = s.utf8.allSatisfy { c in
            (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c == 45 || c == 95
        }
        guard ok, s.utf8.count % 4 != 1 else { return nil }
        var t = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        t += String(repeating: "=", count: (4 - t.utf8.count % 4) % 4)
        guard let d = Data(base64Encoded: t) else { return nil }
        let raw = [UInt8](d)
        return b64urlEncode(raw) == s ? raw : nil
    }

    // MARK: strict JSON

    private struct Reader {
        let s: [UInt8]
        var i = 0

        mutating func ws() {
            while i < s.count, s[i] == 0x20 || s[i] == 0x09 || s[i] == 0x0a || s[i] == 0x0d { i += 1 }
        }

        func starts(_ w: String) -> Bool {
            let b = Array(w.utf8)
            return i + b.count <= s.count && Array(s[i..<i + b.count]) == b
        }

        mutating func value(_ depth: Int) throws -> JSON {
            ws()
            guard i < s.count else { throw Refused("bad_json", "end of text") }
            switch s[i] {
            case UInt8(ascii: "{"): return try obj(depth + 1)
            case UInt8(ascii: "["): return try arr(depth + 1)
            case UInt8(ascii: "\""): return .string(try string())
            case UInt8(ascii: "-"), UInt8(ascii: "0")...UInt8(ascii: "9"): return try number()
            default:
                for (w, v) in [("true", JSON.bool(true)), ("false", JSON.bool(false)), ("null", JSON.null)]
                where starts(w) {
                    i += w.utf8.count
                    return v
                }
                throw Refused("bad_json", "unexpected character")
            }
        }

        mutating func obj(_ depth: Int) throws -> JSON {
            guard depth <= MessageSignature.maxDepth else { throw Refused("bad_json", "too deep") }
            i += 1
            var out: [String: JSON] = [:]
            ws()
            if i < s.count, s[i] == UInt8(ascii: "}") { i += 1; return .object(out) }
            while true {
                ws()
                guard i < s.count, s[i] == UInt8(ascii: "\"") else { throw Refused("bad_json", "key expected") }
                let k = try string()
                guard out[k] == nil else { throw Refused("bad_json", "duplicate key") }
                ws()
                guard i < s.count, s[i] == UInt8(ascii: ":") else { throw Refused("bad_json", "colon expected") }
                i += 1
                out[k] = try value(depth)
                ws()
                guard i < s.count else { throw Refused("bad_json", "end of text") }
                if s[i] == UInt8(ascii: ",") { i += 1; continue }
                if s[i] == UInt8(ascii: "}") { i += 1; return .object(out) }
                throw Refused("bad_json", "comma or } expected")
            }
        }

        mutating func arr(_ depth: Int) throws -> JSON {
            guard depth <= MessageSignature.maxDepth else { throw Refused("bad_json", "too deep") }
            i += 1
            var out: [JSON] = []
            ws()
            if i < s.count, s[i] == UInt8(ascii: "]") { i += 1; return .array(out) }
            while true {
                out.append(try value(depth))
                ws()
                guard i < s.count else { throw Refused("bad_json", "end of text") }
                if s[i] == UInt8(ascii: ",") { i += 1; continue }
                if s[i] == UInt8(ascii: "]") { i += 1; return .array(out) }
                throw Refused("bad_json", "comma or ] expected")
            }
        }

        mutating func hex4() throws -> UInt32 {
            guard i + 4 <= s.count, let t = String(bytes: s[i..<i + 4], encoding: .ascii),
                  t.allSatisfy(\.isHexDigit), let v = UInt32(t, radix: 16)
            else { throw Refused("bad_json", "bad \\u escape") }
            i += 4
            return v
        }

        mutating func string() throws -> String {
            i += 1
            var out = String.UnicodeScalarView()
            while true {
                guard i < s.count else { throw Refused("bad_json", "unterminated string") }
                let c = s[i]
                if c == UInt8(ascii: "\"") {
                    i += 1
                    return String(out)
                }
                if c == UInt8(ascii: "\\") {
                    i += 1
                    guard i < s.count else { throw Refused("bad_json", "bad escape") }
                    let e = s[i]
                    i += 1
                    switch e {
                    case UInt8(ascii: "\""): out.append("\"")
                    case UInt8(ascii: "\\"): out.append("\\")
                    case UInt8(ascii: "/"): out.append("/")
                    case UInt8(ascii: "b"): out.append("\u{8}")
                    case UInt8(ascii: "f"): out.append("\u{c}")
                    case UInt8(ascii: "n"): out.append("\n")
                    case UInt8(ascii: "r"): out.append("\r")
                    case UInt8(ascii: "t"): out.append("\t")
                    case UInt8(ascii: "u"):
                        var cp = try hex4()
                        if (0xD800...0xDBFF).contains(cp) {
                            guard starts("\\u") else { throw Refused("bad_json", "lone surrogate") }
                            i += 2
                            let lo = try hex4()
                            guard (0xDC00...0xDFFF).contains(lo) else { throw Refused("bad_json", "lone surrogate") }
                            cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                        } else if (0xDC00...0xDFFF).contains(cp) {
                            throw Refused("bad_json", "lone surrogate")
                        }
                        guard let u = Unicode.Scalar(cp) else { throw Refused("bad_json", "bad code point") }
                        out.append(u)
                    default: throw Refused("bad_json", "bad escape")
                    }
                    continue
                }
                if c < 0x20 { throw Refused("bad_json", "control character in string") }
                // the whole input was checked as UTF-8 already: decode one scalar
                let len = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4
                guard i + len <= s.count, let str = String(bytes: s[i..<i + len], encoding: .utf8),
                      let u = str.unicodeScalars.first
                else { throw Refused("bad_json", "invalid UTF-8") }
                out.append(u)
                i += len
            }
        }

        mutating func number() throws -> JSON {
            let start = i
            if s[i] == UInt8(ascii: "-") { i += 1 }
            guard i < s.count else { throw Refused("bad_json", "bad number") }
            if s[i] == UInt8(ascii: "0") {
                i += 1
            } else if s[i] >= UInt8(ascii: "1"), s[i] <= UInt8(ascii: "9") {
                while i < s.count, s[i] >= UInt8(ascii: "0"), s[i] <= UInt8(ascii: "9") { i += 1 }
            } else {
                throw Refused("bad_json", "bad number")
            }
            if i < s.count, s[i] == UInt8(ascii: ".") || s[i] == UInt8(ascii: "e") || s[i] == UInt8(ascii: "E") {
                throw Refused("bad_json", "only integers")
            }
            let t = String(decoding: s[start..<i], as: UTF8.self)
            if t == "-0" { throw Refused("bad_json", "-0") }
            guard t.trimmingCharacters(in: CharacterSet(charactersIn: "-")).count <= 16, let n = Int64(t),
                  abs(n) <= MessageSignature.maxSafeInt
            else { throw Refused("bad_json", "integer too large") }
            return .int(n)
        }
    }

    /// The signed bytes as one JSON object, read strictly (same rules as the workspace and the relay).
    static func readStrictJSON(_ data: [UInt8]) throws -> [String: JSON] {
        guard data.count <= maxSignedBytes else { throw Refused("bad_json", "too large") }
        guard data.first == UInt8(ascii: "{"), data.last == UInt8(ascii: "}") else {
            throw Refused("bad_json", "must be one object with nothing around it")
        }
        // Strict UTF-8 (refuses overlong forms, encoded surrogates and bad bytes).
        var it = data.makeIterator()
        var dec = UTF8()
        loop: while true {
            switch dec.decode(&it) {
            case .scalarValue: continue
            case .emptyInput: break loop
            case .error: throw Refused("bad_json", "invalid UTF-8")
            }
        }
        var r = Reader(s: data)
        let v = try r.value(0)
        guard r.i == data.count else { throw Refused("bad_json", "trailing bytes") }
        guard case let .object(o) = v else { throw Refused("bad_json", "not an object") }
        return o
    }

    // MARK: fields

    private static func id(_ s: String?, _ prefix: String, _ min: Int, _ max: Int, hex: Bool = false) -> Bool {
        guard let s, s.hasPrefix(prefix) else { return false }
        let rest = s.utf8.dropFirst(prefix.utf8.count)
        return (min...max).contains(rest.count) && rest.allSatisfy { c in
            (c >= 48 && c <= 57) || (hex ? (c >= 97 && c <= 102) : (c >= 97 && c <= 122))
        }
    }
    private static func isWS(_ s: String?) -> Bool { id(s, "ws_", 10, 10) }
    private static func isPH(_ s: String?) -> Bool { id(s, "ph_", 10, 10) }
    private static func isMsg(_ s: String?) -> Bool { id(s, "m_", 16, 16) }
    private static func isHex64(_ s: String?) -> Bool { id(s, "", 64, 64, hex: true) }

    static let topFields: Set<String> = [
        "v", "id", "from", "to", "type", "created_ms", "origin", "body", "ticket", "reply_to", "question_id",
        "question_sha256", "expires_ms", "files",
    ]

    static func checkFields(_ m: [String: JSON]) throws {
        func bad(_ why: String) -> Refused { Refused("bad_field", why) }
        if m.keys.contains(where: { !topFields.contains($0) }) { throw bad("unknown field") }
        for k in ["v", "id", "from", "to", "type", "created_ms", "origin", "body"] where m[k] == nil {
            throw bad("missing \(k)")
        }
        guard m["v"]?.int == 1 else { throw bad("v") }
        guard isMsg(m["id"]?.string) else { throw bad("id") }
        guard let from = m["from"]?.string, isWS(from) || isPH(from) else { throw bad("from") }
        switch m["to"]! {
        case let .string(to):
            guard isWS(to) || isPH(to) || to == "phones" else { throw bad("to") }
            guard to != from else { throw bad("to equals from") }
            if to == "phones" || isPH(to), !isWS(from) { throw bad("only a workspace sends to phones") }
        case let .object(g):
            guard Set(g.keys) == ["group", "host", "members_v"] else { throw bad("to group fields") }
            guard id(g["group"]?.string, "grp_t_", 6, 16) else { throw bad("to.group") }
            guard isWS(g["host"]?.string) else { throw bad("to.host") }
            guard let n = g["members_v"]?.int, n >= 0 else { throw bad("to.members_v") }
            guard isWS(from) else { throw bad("only a workspace sends to a group") }
        default: throw bad("to")
        }
        if isPH(from), !isWS(m["to"]?.string) { throw bad("a phone sends only to a workspace") }
        guard let typ = m["type"]?.string, types.contains(typ) else { throw bad("type") }
        if m["to"]?.object != nil, !groupTypes.contains(typ) { throw bad("a group message is only text, file or question") }
        guard let created = m["created_ms"]?.int, created > 0 else { throw bad("created_ms") }
        guard let origin = m["origin"]?.string, origin == "person" || origin == "helper" else { throw bad("origin") }
        if isPH(from), origin != "person" { throw bad("a phone signs only as a person") }
        guard m["body"]?.object != nil else { throw bad("body") }
        if m["ticket"] != nil, !id(m["ticket"]?.string, "t_", 6, 16) { throw bad("ticket") }
        if m["reply_to"] != nil, !isMsg(m["reply_to"]?.string) { throw bad("reply_to") }
        if let q = m["question_id"] {
            guard let s = q.string, (1...64).contains(s.utf8.count), s.utf8.allSatisfy({ c in
                (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c == 95 || c == 45
            }) else { throw bad("question_id") }
        }
        if m["question_sha256"] != nil, !isHex64(m["question_sha256"]?.string) { throw bad("question_sha256") }
        if typ == "answer" {
            for k in ["reply_to", "question_id", "question_sha256"] where m[k] == nil { throw bad("answer needs \(k)") }
        } else if m["question_sha256"] != nil || m["question_id"] != nil {
            throw bad("question_id and question_sha256 only on answer")
        }
        if typ == "allow", m["reply_to"] == nil { throw bad("allow needs reply_to") }
        if expiring.contains(typ) {
            guard let e = m["expires_ms"]?.int else { throw bad("\(typ) needs expires_ms") }
            guard created < e, e <= created + maxExpiryMs else { throw bad("expires_ms out of range") }
        } else if m["expires_ms"] != nil {
            throw bad("expires_ms only on allow, delegate, start")
        }
        if let files = m["files"] {
            guard fileTypes.contains(typ) else { throw bad("files not allowed on this type") }
            guard let arr = files.array, (1...maxFiles).contains(arr.count) else { throw bad("files") }
            var seen = Set<String>()
            for f in arr {
                guard let o = f.object, Set(o.keys) == ["blob_id", "size", "sha256"] else { throw bad("file fields") }
                guard let blob = o["blob_id"]?.string, id(blob, "b_", 16, 16), seen.insert(blob).inserted else {
                    throw bad("file blob_id")
                }
                guard let size = o["size"]?.int, (0...maxFileSize).contains(size) else { throw bad("file size") }
                guard isHex64(o["sha256"]?.string) else { throw bad("file sha256") }
            }
        } else if typ == "file" {
            throw bad("file needs files")
        }
    }

    // MARK: envelope, verify, receiver

    struct Envelope {
        let keyId: String
        let signed: [UInt8]
        let sig: [UInt8]
    }

    /// `env` is the decoded wire object (JSONSerialization), or nil when the message had no envelope.
    static func readEnvelope(_ env: Any?) throws -> Envelope {
        guard let env, !(env is NSNull) else { throw Refused("missing_signature", "no envelope") }
        guard let e = env as? [String: Any] else { throw Refused("bad_envelope", "not an object") }
        let allowed: Set<String> = ["sig_v", "key_id", "signed", "sig", "relay_meta"]
        guard e.keys.allSatisfy({ allowed.contains($0) }) else { throw Refused("bad_envelope", "unknown field") }
        guard let v = e["sig_v"] as? NSNumber, CFGetTypeID(v) != CFBooleanGetTypeID(), !CFNumberIsFloatType(v), v == 1 else {
            throw Refused("bad_envelope", "sig_v")
        }
        if let meta = e["relay_meta"], !(meta is [String: Any]) { throw Refused("bad_envelope", "relay_meta") }
        let sigAny = e["sig"]
        if sigAny == nil || sigAny is NSNull || (sigAny as? String) == "" { throw Refused("missing_signature", "no sig") }
        guard let kid = e["key_id"] as? String, kid.utf8.count == 16,
              kid.utf8.allSatisfy({ ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102) })
        else { throw Refused("bad_envelope", "key_id") }
        guard let st = e["signed"] as? String, let signed = b64urlDecodeStrict(st) else {
            throw Refused("bad_envelope", "signed")
        }
        guard let ss = sigAny as? String, let sig = b64urlDecodeStrict(ss) else { throw Refused("bad_envelope", "sig") }
        guard (2...maxSignedBytes).contains(signed.count) else { throw Refused("bad_envelope", "signed size") }
        guard sig.count == 64 else { throw Refused("bad_envelope", "sig size") }
        return Envelope(keyId: kid, signed: signed, sig: sig)
    }

    /// Envelope + trusted keys (owner, raw key) -> (owner, signed object). Duplicate keys count as the same key
    /// when they are the same text in another Unicode spelling (Swift String equality; the workspace and the
    /// relay compare NFC forms).
    static func verify(_ env: Any?, purpose: String, keys: [(String, [UInt8])]) throws -> (String, [String: JSON]) {
        let e = try readEnvelope(env)
        let cands = keys.filter { keyId($0.1) == e.keyId }
        guard !cands.isEmpty else { throw Refused("unknown_key") }
        let data = signatureInput(purpose: purpose, signed: e.signed)
        // every owner of a key that verified; the signed `from` must be one of them (key order never matters)
        let owners = Set(cands.filter { verifyRaw(pub: $0.1, data: data, sig: e.sig) }.map(\.0))
        guard let first = owners.min() else { throw Refused("bad_signature") }
        let m = try readStrictJSON(e.signed)
        if purpose == "msg" {
            try checkFields(m)
            guard let from = m["from"]?.string, owners.contains(from) else { throw Refused("wrong_sender") }
            return (from, m)
        }
        return (first, m)
    }

    /// The receiver's signature, format and freshness checks for a `msg` (an answer still needs its open question). On success the caller marks (from, id) seen
    /// before acting.
    static func receiverCheck(_ env: Any?, me: String, accepted: [String: [[UInt8]]], nowMs: Int64,
                              seen: Set<[String]> = [], groups: Set<[String]> = []) throws -> [String: JSON] {
        let keys = accepted.flatMap { owner, ks in ks.map { (owner, $0) } }
        let (_, m) = try verify(env, purpose: "msg", keys: keys)
        let from = m["from"]!.string!
        if from == me { throw Refused("from_self") }
        let ok: Bool
        switch m["to"]! {
        case let .object(g):
            ok = me.hasPrefix("ws_") && groups.contains([g["host"]!.string!, g["group"]!.string!])
        case let .string(to):
            ok = to == me || (to == "phones" && me.hasPrefix("ph_"))
        default:
            ok = false
        }
        guard ok else { throw Refused("wrong_to") }
        let created = m["created_ms"]!.int!
        if created > nowMs + futureSkewMs { throw Refused("future") }
        if let exp = m["expires_ms"]?.int {
            if nowMs >= exp { throw Refused("expired") }
        } else if created < nowMs - maxAgeMs {
            throw Refused("too_old")
        }
        if seen.contains([from, m["id"]!.string!]) { throw Refused("replayed") }
        return m
    }
}
