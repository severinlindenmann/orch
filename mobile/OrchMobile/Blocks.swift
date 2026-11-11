import Foundation
import CoreFoundation

/// Invalid results retain their source only for the collapsed Details disclosure.
enum BlocksResult {
    case invalid(rawJSON: String)
    case shown(BlocksDoc)

    static func decode(_ data: Data) -> BlocksResult {
        let raw = String(decoding: data, as: UTF8.self)
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return .invalid(rawJSON: raw)
        }
        return decode(object, raw: raw)
    }

    static func decode(_ object: [String: Any]) -> BlocksResult { decode(object, raw: nil) }

    private static func decode(_ object: [String: Any], raw: String?) -> BlocksResult {
        let compact = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        let source = raw ?? compact.map { String(decoding: $0, as: UTF8.self) } ?? String(describing: object)
        guard let compact, compact.count <= 65_536, BlocksValidation.document(object),
              // Plain decoder on purpose: JSONCoding's convertFromSnakeCase also rewrites dictionary keys (total_rows, column keys).
              let doc = try? JSONDecoder().decode(BlocksDocumentInput.self, from: compact) else {
            return .invalid(rawJSON: source)
        }
        return .shown(BlocksDoc(from: doc.from, title: doc.title, rows: doc.blocks.map(BlockRow.init)))
    }
}

struct BlocksDoc {
    let from: String
    let title: String?
    let rows: [BlockRow]
    var fromLabel: String { from == "job" ? "Reported by the job" : from == "agent" ? "Proof" : "From orch" }
    var texts: [String] { [fromLabel] + (title.map { [$0] } ?? []) + rows.flatMap(\.texts) }
    var fallbackCount: Int { rows.filter { if case .unsupported = $0 { return true }; return false }.count }
}

private struct BlocksDocumentInput: Decodable {
    let from: String
    let title: String?
    let blocks: [BlockFields]
}

/// JSON dictionary decoding preserves table keys (including underscores).
indirect enum BlockValue: Decodable {
    case string(String), number(Double), null, array([BlockValue]), object([String: BlockValue]), bool(Bool)
    /// Nesting cap: hostile deeply nested values must fail cleanly, not overflow the stack (no block needs > ~10 levels).
    static let maxDepth = 40
    init(from decoder: Decoder) throws {
        guard decoder.codingPath.count <= Self.maxDepth else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "nested too deep"))
        }
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([BlockValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: BlockValue].self)) }
    }
    var string: String? { if case .string(let s) = self { return s }; return nil }
    var number: Double? { if case .number(let n) = self { return n }; return nil }
    var array: [BlockValue] { if case .array(let a) = self { return a }; return [] }
    var fields: BlockFields { if case .object(let o) = self { return BlockFields(values: o) }; return BlockFields(values: [:]) }
}

struct BlockFields: Decodable {
    let values: [String: BlockValue]
    init(values: [String: BlockValue]) { self.values = values }
    init(from decoder: Decoder) throws { values = try decoder.singleValueContainer().decode([String: BlockValue].self) }
    func text(_ key: String) -> String? { values[key]?.string }
    func number(_ key: String) -> Double? { values[key]?.number }
    func list(_ key: String) -> [BlockValue] { values[key]?.array ?? [] }
    func objects(_ key: String) -> [BlockFields] { list(key).map(\.fields) }
    var heading: [String] { text("title").map { [$0] } ?? [] }
    var progressText: String {
        BlocksFormat.number(number("done") ?? 0) + (number("total").map { " of " + BlocksFormat.number($0) } ?? "") + unitSuffix
    }
    var unitSuffix: String { text("unit").map { " " + $0 } ?? "" }
    var statText: String { BlocksFormat.cell(values["value"]) + unitSuffix }
    var fileName: String { text("label") ?? (text("path") ?? "").components(separatedBy: "/").last ?? "" }
    var sizeText: String? { number("size").map(BlocksFormat.size) }
    var tableFooter: String? {
        number("total_rows").map { "\(list("rows").count) of \(BlocksFormat.number($0)) rows" }
    }
    var chartLabel: String { (heading + objects("series").compactMap { $0.text("name") }).joined(separator: ", ") }
}

enum BlockRow {
    case summary(BlockFields), steps(BlockFields), progress(BlockFields), stat(BlockFields), kv(BlockFields)
    case table(BlockFields), file(BlockFields), link(BlockFields), log(BlockFields), chart(BlockFields), unsupported
    init(_ b: BlockFields) {
        switch b.text("type") {
        case "summary": self = .summary(b)
        case "steps": self = .steps(b)
        case "progress": self = .progress(b)
        case "stat": self = .stat(b)
        case "kv": self = .kv(b)
        case "table": self = .table(b)
        case "file": self = .file(b)
        case "link": self = .link(b)
        case "log": self = .log(b)
        case "chart": self = .chart(b)
        default: self = .unsupported
        }
    }
    var texts: [String] {
        switch self {
        case .unsupported: return ["can't show this here"]
        case .summary(let b): return [b.text("text") ?? ""]
        case .steps(let b): return b.objects("items").flatMap { [$0.text("label"), $0.text("note"), $0.text("state")].compactMap { $0 } }
        case .progress(let b): return [b.text("label") ?? "", b.progressText]
        case .stat(let b): return [b.text("label"), b.statText, b.text("delta")].compactMap { $0 }
        case .kv(let b): return b.objects("items").flatMap { [$0.text("key") ?? "", BlocksFormat.cell($0.values["value"])] }
        case .table(let b):
            let columns = b.objects("columns")
            return b.heading + columns.compactMap { $0.text("label") } + b.objects("rows").flatMap { row in
                columns.map { BlocksFormat.cell(row.values[$0.text("key") ?? ""], kind: $0.text("kind")) }
            } + (b.tableFooter.map { [$0] } ?? [])
        case .file(let b): return [b.fileName] + (b.sizeText.map { [$0] } ?? [])
        case .link(let b): return [b.text("label") ?? ""]
        case .log(let b): return b.heading + b.list("lines").compactMap(\.string) + (b.number("cut") != nil ? ["Cut"] : [])
        case .chart(let b): return b.heading + [b.text("x_label"), b.text("y_label")].compactMap { $0 } + b.objects("series").flatMap { s in
            [s.text("name") ?? ""] + s.list("points").flatMap { $0.array.map { BlocksFormat.cell($0) } }
        }
        }
    }
}

enum BlocksFormat {
    nonisolated(unsafe) private static let formatter: NumberFormatter = {
        let f = NumberFormatter(); f.locale = Locale(identifier: "en_US_POSIX")
        f.numberStyle = .decimal; f.groupingSeparator = " "; f.maximumFractionDigits = 12
        return f
    }()
    static func number(_ value: Double) -> String {
        formatter.string(from: NSNumber(value: value)) ?? String(value)
    }
    static func size(_ bytes: Double) -> String {
        if bytes < 1024 { return number(bytes) + " B" }
        if bytes < 1_048_576 { return number((bytes / 1024 * 10).rounded() / 10) + " KB" }
        return number((bytes / 1_048_576 * 10).rounded() / 10) + " MB"
    }
    static func cell(_ value: BlockValue?, kind: String? = nil) -> String {
        guard let value else { return "—" }
        if case .number(let n) = value {
            if kind == "duration" {
                if n < 60 { return number(n) + " s" }
                if n < 3600 { return number(floor(n / 60)) + " m " + number(n.truncatingRemainder(dividingBy: 60)) + " s" }
                return number(floor(n / 3600)) + " h " + number(floor(n.truncatingRemainder(dividingBy: 3600) / 60)) + " m"
            }
            return number(n)
        }
        if case .string(let s) = value {
            if kind == "date" {
                let iso = ISO8601DateFormatter()
                var date = iso.date(from: s)
                if date == nil { iso.formatOptions.insert(.withFractionalSeconds); date = iso.date(from: s) }
                if let date {
                    let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = TimeZone(secondsFromGMT: 0)
                    f.dateFormat = "yyyy-MM-dd HH:mm:ss 'UTC'"; return f.string(from: date)
                }
            }
            return s
        }
        return "—"
    }
}

private enum BlocksValidation {
    static func match(_ s: String, _ pattern: String) -> Bool {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return false }
        let range = NSRange(s.startIndex..., in: s)
        return regex.firstMatch(in: s, range: range)?.range == range
    }
    static func string(_ v: Any?, max: Int = 200, min: Int = 1, allowed: Set<UInt32> = []) -> Bool {
        guard let s = v as? String, (min...max).contains(s.unicodeScalars.count) else { return false }
        return s.unicodeScalars.allSatisfy { ($0.value >= 32 && $0.value != 127) || allowed.contains($0.value) }
    }
    static func number(_ v: Any?) -> Double? {
        guard let n = v as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite else { return nil }
        return n.doubleValue
    }
    static func integer(_ v: Any?) -> Bool { guard let n = number(v) else { return false }; return n >= 0 && n.rounded() == n }
    static func cell(_ v: Any?) -> Bool { v is NSNull || number(v) != nil || string(v, min: 0) }
    static func fields(_ o: [String: Any], _ required: [String], _ optional: [String] = []) -> Bool {
        Set(required).isSubset(of: Set(o.keys)) && Set(o.keys).isSubset(of: Set(required + optional))
    }
    static func optional(_ o: [String: Any], _ key: String, _ check: (Any?) -> Bool) -> Bool { o[key] == nil || check(o[key]) }
    static func one(_ v: Any?, _ choices: [String]) -> Bool { (v as? String).map(choices.contains) ?? false }
    static func items(_ v: Any?, min: Int = 0, max: Int, _ check: (Any) -> Bool) -> Bool {
        guard let a = v as? [Any], (min...max).contains(a.count) else { return false }; return a.allSatisfy(check)
    }
    static func document(_ o: [String: Any]) -> Bool {
        fields(o, ["schema", "from", "blocks"], ["title"]) && o["schema"] as? String == "orch.blocks/1"
        && one(o["from"], ["job", "agent", "orch"]) && optional(o, "title") { string($0) }
        && items(o["blocks"], max: 50) { block($0) }
    }
    static func path(_ v: Any?) -> Bool {
        guard string(v, max: 300), let path = v as? String else { return false }
        var rest = path
        if let range = rest.range(of: #"^\.orch/tickets/t_[a-z0-9]{6,16}/artifacts/"#, options: .regularExpression) { rest.removeSubrange(range) }
        return !rest.isEmpty && !rest.hasPrefix("/") && !rest.contains("\\")
            && rest.range(of: #"^[A-Za-z]:"#, options: .regularExpression) == nil
            && !rest.components(separatedBy: "/").contains { $0.hasPrefix(".") }
    }
    static func block(_ value: Any) -> Bool {
        guard let o = value as? [String: Any], let type = o["type"] as? String, match(type, "[a-z][a-z0-9-]{0,31}") else { return false }
        let line: (Any?) -> Bool = { string($0) }, short: (Any?) -> Bool = { string($0, max: 64) }
        let tone: (Any?) -> Bool = { one($0, ["neutral", "good", "warn", "bad"]) }
        switch type {
        case "summary": return fields(o, ["type", "text"], ["tone"]) && string(o["text"], max: 2000, allowed: [9, 10]) && optional(o, "tone", tone)
        case "steps": return fields(o, ["type", "items"]) && items(o["items"], min: 1, max: 100) {
            guard let i = $0 as? [String: Any] else { return false }
            return fields(i, ["label", "state"], ["note"]) && line(i["label"]) && one(i["state"], ["waiting", "running", "done", "failed", "skipped"]) && optional(i, "note", line)
        }
        case "progress": return fields(o, ["type", "label", "done", "total"], ["unit"]) && line(o["label"])
            && (number(o["done"]).map { $0 >= 0 } ?? false) && (o["total"] is NSNull || (number(o["total"]).map { $0 > 0 } ?? false)) && optional(o, "unit", short)
        case "stat": return fields(o, ["type", "label", "value"], ["unit", "tone", "delta"]) && line(o["label"])
            && (number(o["value"]) != nil || short(o["value"])) && optional(o, "unit", short) && optional(o, "tone", tone) && optional(o, "delta", short)
        case "kv": return fields(o, ["type", "items"]) && items(o["items"], min: 1, max: 50) {
            guard let i = $0 as? [String: Any] else { return false }; return fields(i, ["key", "value"]) && line(i["key"]) && cell(i["value"])
        }
        case "table": return fields(o, ["type", "columns", "rows"], ["title", "total_rows"]) && optional(o, "title", line) && optional(o, "total_rows", integer)
            && items(o["columns"], min: 1, max: 12) {
                guard let c = $0 as? [String: Any], let key = c["key"] as? String else { return false }
                return fields(c, ["key", "label"], ["kind"]) && match(key, "[a-z][a-z0-9_]{0,31}") && short(c["label"])
                    && optional(c, "kind") { one($0, ["text", "number", "duration", "date", "tone"]) }
            } && items(o["rows"], max: 200) {
                guard let r = $0 as? [String: Any], r.count <= 12 else { return false }
                return r.allSatisfy { match($0.key, "[a-z][a-z0-9_]{0,31}") && cell($0.value) }
            }
        case "file": return fields(o, ["type", "path"], ["label", "size", "preview"]) && path(o["path"]) && optional(o, "label", line)
            && optional(o, "size", integer) && optional(o, "preview") { one($0, ["image"]) }
        case "link":
            guard fields(o, ["type", "url", "label"]), line(o["label"]), let s = o["url"] as? String,
                  s.unicodeScalars.count <= 2000, match(s, #"https://(?![^/?#]*@)[^\s<>"'`]+"#),
                  let u = URLComponents(string: s), u.scheme == "https", let host = u.host, !host.isEmpty,
                  u.user == nil, u.password == nil else { return false }
            return true
        case "log": return fields(o, ["type", "lines"], ["title", "cut"]) && optional(o, "title", line) && optional(o, "cut", integer)
            && items(o["lines"], max: 200) { string($0, max: 500, min: 0, allowed: [9]) }
        case "chart": return fields(o, ["type", "kind", "series"], ["title", "x_label", "y_label"]) && one(o["kind"], ["line", "bar"])
            && optional(o, "title", line) && optional(o, "x_label", short) && optional(o, "y_label", short)
            && items(o["series"], min: 1, max: 4) {
                guard let s = $0 as? [String: Any] else { return false }
                return fields(s, ["name", "points"]) && short(s["name"]) && items(s["points"], max: 200) {
                    guard let p = $0 as? [Any], p.count == 2 else { return false }
                    return (number(p[0]) != nil || short(p[0])) && (p[1] is NSNull || number(p[1]) != nil)
                }
            }
        default: return true
        }
    }
}
