import Foundation

/// The envelope is strict; a malformed document belongs to the renderer's invalid state.
struct TicketResult: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let from: String
    let title: String?
    let at: String
    let checked: Bool
    let rawDoc: Data
    var doc: BlocksResult { BlocksResult.decode(rawDoc) }

    // contracts/blocks.md keeps agent source labels; the phone displays helper wording only.
    var label: String {
        switch from {
        case "job": "Reported by the job"
        case "agent": checked ? "Checked by the helper" : "From the helper"
        default: "Worked out by orch"
        }
    }

    init(from decoder: Decoder) throws {
        // Dictionary keys bypass JSONCoding's snake-case conversion, including inside doc.
        let c = try decoder.singleValueContainer()
        let fields = try c.decode([String: ResultJSON].self)
        guard Set(fields.keys).isSubset(of: ["id", "from", "title", "at", "checked", "doc"]),
              let id = fields["id"]?.string,
              id.range(of: #"\A(j_[a-z0-9]{6,32}|a_[0-9a-f]{12})\z"#, options: .regularExpression) != nil,
              let from = fields["from"]?.string, ["job", "agent", "orch"].contains(from),
              let at = fields["at"]?.string, at.hasSuffix("Z"), Self.date(at) != nil,
              case .object(let document)? = fields["doc"], document["from"]?.string == from,
              fields["checked"] == nil || (fields["checked"] == .bool(true) && from == "agent"),
              fields["title"] == nil || fields["title"]?.string.map(Self.validTitle) == true else {
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "Invalid ticket result envelope")
        }
        self.id = id; self.from = from; self.at = at
        title = fields["title"]?.string.flatMap { Self.displaySafe($0) ? $0 : nil }; checked = fields["checked"] == .bool(true)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        rawDoc = try encoder.encode(document)
    }

    func encode(to encoder: Encoder) throws {
        var fields: [String: ResultJSON] = ["id": .string(id), "from": .string(from), "at": .string(at),
                                          "doc": try JSONDecoder().decode(ResultJSON.self, from: rawDoc)]
        if let title { fields["title"] = .string(title) }
        if checked { fields["checked"] = .bool(true) }
        var c = encoder.singleValueContainer()
        try c.encode(fields)
    }

    /// Schema: 1-200 characters, no control characters (a line break could fake a label line).
    static func validTitle(_ t: String) -> Bool {
        (1...200).contains(t.unicodeScalars.count) && !t.unicodeScalars.contains { $0.value < 32 || $0.value == 127 }
    }

    /// Schema-valid but could fake a second line or reorder text next to the label (U+0085, U+2028/29, C1, bidi
    /// controls): the result stays, only its title is not shown.
    static func displaySafe(_ t: String) -> Bool {
        !t.unicodeScalars.contains { v in
            v.properties.isBidiControl || (0x80...0x9F).contains(v.value) || v.value == 0x2028 || v.value == 0x2029
        }
    }

    static func date(_ value: String) -> Date? {
        guard value.range(of: #"\A[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})\z"#,
                          options: .regularExpression) != nil else { return nil }
        let formatter = ISO8601DateFormatter()
        let normalized = value.uppercased()
        if let date = formatter.date(from: normalized) { return date }
        formatter.formatOptions.insert(.withFractionalSeconds)
        return formatter.date(from: normalized)
    }

    static func decodeList<K: CodingKey>(_ c: KeyedDecodingContainer<K>, forKey key: K) -> [TicketResult] {
        guard var list = try? c.nestedUnkeyedContainer(forKey: key) else { return [] }
        var seen = Set<String>()
        var items: [(result: TicketResult, date: Date, index: Int)] = []
        while !list.isAtEnd {
            // superDecoder advances once even when the item's own decode throws.
            guard let decoder = try? list.superDecoder() else { break }
            if let result = try? TicketResult(from: decoder), seen.insert(result.id).inserted,
               let date = date(result.at) {
                items.append((result, date, items.count))
            }
        }
        return items.sorted {
            $0.date == $1.date ? $0.index < $1.index : $0.date > $1.date
        }.prefix(5).map(\.result)
    }

    static func attachment(named path: String, in attachments: [TicketSnapshot.Attachment]) -> TicketSnapshot.Attachment? {
        let name = path.components(separatedBy: "/").last ?? path
        return attachments.first { $0.isBlob && $0.name?.caseInsensitiveCompare(name) == .orderedSame }
    }
}

/// Lossless JSON shape for storage; dictionary keys are never rewritten by key strategies.
private indirect enum ResultJSON: Codable, Equatable {
    case string(String), number(Double), bool(Bool), null, array([ResultJSON]), object([String: ResultJSON])
    var string: String? { if case .string(let value) = self { return value }; return nil }
    init(from decoder: Decoder) throws {
        // Same nesting cap as BlockValue: deep hostile input fails this item cleanly instead of overflowing the stack.
        guard decoder.codingPath.count <= BlockValue.maxDepth else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "nested too deep"))
        }
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let value = try? c.decode(Bool.self) { self = .bool(value) }
        else if let value = try? c.decode(String.self) { self = .string(value) }
        else if let value = try? c.decode(Double.self) { self = .number(value) }
        else if let value = try? c.decode([ResultJSON].self) { self = .array(value) }
        else { self = .object(try c.decode([String: ResultJSON].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let value): try c.encode(value)
        case .number(let value): try c.encode(value)
        case .bool(let value): try c.encode(value)
        case .null: try c.encodeNil()
        case .array(let value): try c.encode(value)
        case .object(let value): try c.encode(value)
        }
    }
}
