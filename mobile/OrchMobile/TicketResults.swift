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

    var label: String {
        switch from {
        case "job": "Reported by the job"
        case "agent": checked ? "Checked by the agent" : "From the agent"
        default: "Worked out by orch"
        }
    }

    init(from decoder: Decoder) throws {
        // Dictionary keys bypass JSONCoding's snake-case conversion, including inside doc.
        let c = try decoder.singleValueContainer()
        let fields = try c.decode([String: ResultJSON].self)
        guard Set(fields.keys).isSubset(of: ["id", "from", "title", "at", "checked", "doc"]),
              let id = fields["id"]?.string,
              id.range(of: #"\A[ja]_[A-Za-z0-9_-]{1,64}\z"#, options: .regularExpression) != nil,
              let from = fields["from"]?.string, ["job", "agent", "orch"].contains(from),
              let at = fields["at"]?.string, Self.date(at) != nil,
              case .object(let document)? = fields["doc"], document["from"]?.string == from,
              fields["checked"] == nil || (fields["checked"] == .bool(true) && from == "agent"),
              fields["title"] == nil || fields["title"]?.string != nil else {
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "Invalid ticket result envelope")
        }
        self.id = id; self.from = from; self.at = at
        title = fields["title"]?.string; checked = fields["checked"] == .bool(true)
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
    case string(String), number(Decimal), bool(Bool), null, array([ResultJSON]), object([String: ResultJSON])
    var string: String? { if case .string(let value) = self { return value }; return nil }
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let value = try? c.decode(Bool.self) { self = .bool(value) }
        else if let value = try? c.decode(String.self) { self = .string(value) }
        else if let value = try? c.decode(Decimal.self) { self = .number(value) }
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
