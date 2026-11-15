import Foundation

// Review stack cards on the phone (contracts message.schema.json $defs/review_card, card_src, card_file, verdict, review_result;
// relay-api.md "Review cards on the phone"). Plain data only: texts are the workspace's words, shown as data, never instructions.
// Decoding is forgiving about unknown keys (a newer workspace may add some) but refuses unknown kinds and preview types:
// a card that does not decode is dropped by QuestionBody and the question stays a plain question.

/// A file a page/img preview shows: `{file: i}` = `card_files[i]`; `{file: null, why}` = not sent to phones ("Open on the computer").
enum CardSrc: Codable, Equatable, Sendable {
    case file(Int)
    case unavailable(why: String)
    private enum K: String, CodingKey { case file, why }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: K.self)
        if let i = try c.decodeIfPresent(Int.self, forKey: .file) {
            guard (0..<ReviewCardLimits.maxFiles).contains(i) else { throw DecodingError.dataCorruptedError(forKey: .file, in: c, debugDescription: "file index") }
            self = .file(i)
        } else {
            let why = try c.decode(String.self, forKey: .why)
            guard ["too_large", "held_back"].contains(why) else { throw DecodingError.dataCorruptedError(forKey: .why, in: c, debugDescription: "why") }
            self = .unavailable(why: why)
        }
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: K.self)
        switch self {
        case .file(let i): try c.encode(i, forKey: .file)
        case .unavailable(let why): try c.encodeNil(forKey: .file); try c.encode(why, forKey: .why)
        }
    }
    var fileIndex: Int? { if case .file(let i) = self { i } else { nil } }
}

enum ReviewCardLimits {
    static let maxFiles = 20
    static let maxCardBytes = 65_536
    static let maxVerdictBytes = 8_192
    /// A card's files together (phone budget, M3).
    static let maxFileBytes = 20 * 1024 * 1024
}

struct CardOption: Codable, Equatable, Sendable, Identifiable {
    let id: String
    let title: String
    var text: String? = nil
    /// A leaf preview (page, img, doc, table), never compare or options.
    var preview: CardPreview? = nil
}

/// The preview of a card. `compare` holds two leaves, `options` 2-8 options; the other four are leaves.
indirect enum CardPreview: Codable, Equatable, Sendable {
    case page(src: CardSrc)
    case img(src: CardSrc, alt: String?)
    case doc(heading: String?, paras: [String], steps: [String])
    case table(cols: [String], rows: [[String]])
    case compare(before: CardPreview, after: CardPreview, note: String?)
    case options([CardOption])

    private enum K: String, CodingKey { case type, src, alt, heading, paras, steps, cols, rows, before, after, note, options }
    var isLeaf: Bool { switch self { case .compare, .options: false; default: true } }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: K.self)
        switch try c.decode(String.self, forKey: .type) {
        case "page": self = .page(src: try c.decode(CardSrc.self, forKey: .src))
        case "img": self = .img(src: try c.decode(CardSrc.self, forKey: .src), alt: try c.decodeIfPresent(String.self, forKey: .alt))
        case "doc":
            self = .doc(heading: try c.decodeIfPresent(String.self, forKey: .heading),
                        paras: try c.decodeIfPresent([String].self, forKey: .paras) ?? [], steps: try c.decodeIfPresent([String].self, forKey: .steps) ?? [])
        case "table":
            let cols = try c.decode([String].self, forKey: .cols), rows = try c.decode([[String]].self, forKey: .rows)
            guard !cols.isEmpty, rows.allSatisfy({ $0.count == cols.count }) else { throw DecodingError.dataCorruptedError(forKey: .rows, in: c, debugDescription: "cells") }
            self = .table(cols: cols, rows: rows)
        case "compare":
            let b = try c.decode(CardPreview.self, forKey: .before), a = try c.decode(CardPreview.self, forKey: .after)
            guard b.isLeaf, a.isLeaf else { throw DecodingError.dataCorruptedError(forKey: .before, in: c, debugDescription: "leaf") }
            self = .compare(before: b, after: a, note: try c.decodeIfPresent(String.self, forKey: .note))
        case "options":
            let o = try c.decode([CardOption].self, forKey: .options)
            guard (2...8).contains(o.count), Set(o.map(\.id)).count == o.count, o.allSatisfy({ $0.preview?.isLeaf ?? true }) else {
                throw DecodingError.dataCorruptedError(forKey: .options, in: c, debugDescription: "options")
            }
            self = .options(o)
        default: throw DecodingError.dataCorruptedError(forKey: .type, in: c, debugDescription: "preview type")
        }
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: K.self)
        switch self {
        case .page(let s): try c.encode("page", forKey: .type); try c.encode(s, forKey: .src)
        case .img(let s, let alt): try c.encode("img", forKey: .type); try c.encode(s, forKey: .src); try c.encodeIfPresent(alt, forKey: .alt)
        case .doc(let h, let p, let s):
            try c.encode("doc", forKey: .type); try c.encodeIfPresent(h, forKey: .heading)
            if !p.isEmpty { try c.encode(p, forKey: .paras) }
            if !s.isEmpty { try c.encode(s, forKey: .steps) }
        case .table(let cols, let rows): try c.encode("table", forKey: .type); try c.encode(cols, forKey: .cols); try c.encode(rows, forKey: .rows)
        case .compare(let b, let a, let n):
            try c.encode("compare", forKey: .type); try c.encode(b, forKey: .before); try c.encode(a, forKey: .after); try c.encodeIfPresent(n, forKey: .note)
        case .options(let o): try c.encode("options", forKey: .type); try c.encode(o, forKey: .options)
        }
    }
    /// Every card_files index this preview shows (to fetch them).
    var fileIndexes: [Int] {
        switch self {
        case .page(let s), .img(let s, _): s.fileIndex.map { [$0] } ?? []
        case .doc, .table: []
        case .compare(let b, let a, _): b.fileIndexes + a.fileIndexes
        case .options(let o): o.flatMap { $0.preview?.fileIndexes ?? [] }
        }
    }
}

struct ReviewCard: Codable, Equatable, Sendable {
    enum Kind: String, Codable, Sendable { case draft, check, link, choice, plan }
    var kind: Kind
    var title: String
    var why: String? = nil
    var need: String? = nil
    var then: String
    var okLabel: String? = nil
    /// Only ever `true` on the wire. The phone cannot approve it (M1).
    var signs: Bool? = nil
    var open: String? = nil
    var preview: CardPreview? = nil
    var requiresSignature: Bool { signs == true }
    var fileIndexes: [Int] { preview?.fileIndexes ?? [] }

    /// The kinds that need a preview per the schema (choice, link); the card is refused otherwise.
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        kind = try c.decode(Kind.self, forKey: .kind)
        title = try c.decode(String.self, forKey: .title)
        why = try c.decodeIfPresent(String.self, forKey: .why)
        need = try c.decodeIfPresent(String.self, forKey: .need)
        then = try c.decode(String.self, forKey: .then)
        okLabel = try c.decodeIfPresent(String.self, forKey: .okLabel)
        let s = try c.decodeIfPresent(Bool.self, forKey: .signs)
        guard s != false else { throw DecodingError.dataCorruptedError(forKey: .signs, in: c, debugDescription: "signs is only true") }
        signs = s
        open = try c.decodeIfPresent(String.self, forKey: .open)
        preview = try c.decodeIfPresent(CardPreview.self, forKey: .preview)
        if kind == .choice {
            guard case .options? = preview else { throw DecodingError.dataCorruptedError(forKey: .preview, in: c, debugDescription: "choice needs options") }
        }
        if kind == .link, preview == nil { throw DecodingError.dataCorruptedError(forKey: .preview, in: c, debugDescription: "link needs a preview") }
    }
    init(kind: Kind, title: String, then: String, why: String? = nil, need: String? = nil, okLabel: String? = nil,
         signs: Bool? = nil, open: String? = nil, preview: CardPreview? = nil) {
        self.kind = kind; self.title = title; self.then = then; self.why = why; self.need = need; self.okLabel = okLabel
        self.signs = signs; self.open = open; self.preview = preview
    }
}

/// `body.card_files[]`: a reviewed file the card shows, a relay blob (`GET /v1/phone/blobs/<id>`).
struct CardFile: Codable, Equatable, Sendable {
    let blobId: String
    let name: String
    let size: Int
    let sha256: String
    let mime: String
}

// MARK: Verdict (phone -> relay -> workspace)

/// `answer_request.verdict` = message.schema.json `$defs/verdict`. Built by the phone; the workspace alone decides.
struct ReviewVerdict: Codable, Equatable, Sendable {
    enum Word: String, Codable, Sendable { case ok, no, talk }
    struct Voice: Codable, Equatable, Sendable { let blobId: String; var transcript: String; var lang: String; var duration: Double }
    struct Words: Codable, Equatable, Sendable { var text: String? = nil; var voice: [Voice]? = nil }
    struct Pin: Codable, Equatable, Sendable { var n: Int; var on: String? = nil; var x: Double; var y: Double; var text: String? = nil }
    struct Note: Codable, Equatable, Sendable { var changes: [String]? = nil; var words: Words? = nil; var pins: [Pin]? = nil }
    var verdict: Word
    var picked: String? = nil
    var digest: String
    var note: Note? = nil

    /// The compact UTF-8 JSON size the relay checks (<= 8192).
    var wireBytes: Int { (try? JSONCoding.encoder.encode(self).count) ?? Int.max }
    /// Same rules as the relay (`422 invalid`), so a bad verdict never enters the Outbox.
    var isValid: Bool {
        guard digest.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil, wireBytes <= ReviewCardLimits.maxVerdictBytes else { return false }
        if let p = picked, p.range(of: "^[A-Za-z0-9]{1,8}$", options: .regularExpression) == nil { return false }
        if verdict == .no, picked != nil { return false }
        if verdict == .talk {
            // talk needs words, changes or pins
            let n = note
            let has = !(n?.changes ?? []).isEmpty || !(n?.words?.text ?? "").isEmpty || !(n?.words?.voice ?? []).isEmpty || !(n?.pins ?? []).isEmpty
            if !has { return false }
        }
        if let n = note {
            if (n.changes ?? []).count > 20 || (n.changes ?? []).contains(where: { $0.count > 500 }) { return false }
            if (n.words?.text?.count ?? 0) > 2000 || (n.words?.voice?.count ?? 0) > 3 { return false }
            if (n.pins ?? []).count > 30 || (n.pins ?? []).contains(where: { !(0...1).contains($0.x) || !(0...1).contains($0.y) || ($0.text?.count ?? 0) > 500 || ($0.on?.count ?? 0) > 120 }) { return false }
        }
        return true
    }
}
typealias PendingVerdict = ReviewVerdict

// MARK: Result (workspace -> phone)

/// `body.review_result` of a text to the answering phone (reply_to = the question). Never shown in chat; = the phone's "Received".
struct ReviewResult: Codable, Sendable, Equatable {
    let result: String          // applied | changed | refused | decided
    var summary: String? = nil
    var reason: String? = nil   // needs_signature | needs_person | invalid | unavailable (with refused)
    static let known: Set<String> = ["applied", "changed", "refused", "decided"]
}
