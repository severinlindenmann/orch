import Foundation

/// One reference of a ticket (`ticket_view.refs`, contracts/message.schema.json): a web address, another ticket, a file the
/// ticket produced, or a project file. Add-on kinds (`github:pr`, ...) that carry an address are shown as web addresses.
struct TicketRef: Codable, Sendable, Equatable {
    enum Kind: Equatable, Sendable { case url, ticket, artifact, file }
    var rawKind: String
    var url: String? = nil
    var ticket: String? = nil
    var name: String? = nil
    var path: String? = nil
    var line: Int? = nil
    var title: String? = nil
    var status: String? = nil

    enum CodingKeys: String, CodingKey { case rawKind = "kind", url, ticket, name, path, line, title, status }

    init(rawKind: String, url: String? = nil, ticket: String? = nil, name: String? = nil, path: String? = nil, line: Int? = nil,
         title: String? = nil, status: String? = nil) {
        self.rawKind = rawKind; self.url = url; self.ticket = ticket; self.name = name; self.path = path; self.line = line
        self.title = title; self.status = status
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        rawKind = try c.decode(String.self, forKey: .rawKind)
        url = try? c.decodeIfPresent(String.self, forKey: .url); ticket = try? c.decodeIfPresent(String.self, forKey: .ticket)
        name = try? c.decodeIfPresent(String.self, forKey: .name); path = try? c.decodeIfPresent(String.self, forKey: .path)
        line = try? c.decodeIfPresent(Int.self, forKey: .line); title = try? c.decodeIfPresent(String.self, forKey: .title)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
    }

    /// What the phone can show, or nil (unknown kind, or the field the kind needs is missing).
    var kind: Kind? {
        switch rawKind {
        case "url": return url != nil ? .url : nil
        case "ticket": return ticket != nil ? .ticket : nil
        case "artifact": return name != nil ? .artifact : nil
        case "file": return path != nil ? .file : nil
        default: return rawKind.contains(":") && url != nil ? .url : nil   // add-on kind with an address
        }
    }

    /// "docs/spec.md:40"
    var pathText: String? { path.map { p in line.map { "\(p):\($0)" } ?? p } }

    /// Decodes the list one item at a time: a bad or unknown item is skipped, never fails the snapshot.
    static func decodeList<K: CodingKey>(_ c: KeyedDecodingContainer<K>, forKey key: K) -> [TicketRef] {
        guard var list = try? c.nestedUnkeyedContainer(forKey: key) else { return [] }
        var out: [TicketRef] = []
        while !list.isAtEnd {
            if let ref = try? list.decode(TicketRef.self) { if ref.kind != nil { out.append(ref) } }
            else { _ = try? list.decode(Skip.self) }   // advance past the broken item
        }
        return Array(out.prefix(50))
    }
    private struct Skip: Decodable { init(from d: Decoder) throws {} }
}

/// A reference ready to draw (the References section of the info screen).
enum RefRow: Equatable, Identifiable {
    /// A web address: opened only when it is a plain https/http address (SafeLink).
    case link(id: String, title: String, host: String, url: URL)
    /// Another ticket: "PIL-12 · title". `known` = the phone has that topic, so a tap opens it.
    case ticket(id: String, label: String, known: Bool)
    /// A file a ticket produced; `item` is set when the phone has it in a ticket's results.
    case artifact(id: String, name: String, item: ArtifactItem?)
    /// A project file: plain "path:line" text, no action.
    case file(id: String, text: String)

    var id: String {
        switch self { case .link(let id, _, _, _), .ticket(let id, _, _), .artifact(let id, _, _), .file(let id, _): id }
    }

    /// `lookup` gives a ticket's display key and title; `attachments` finds an artifact by ticket id and file name.
    static func rows(_ refs: [TicketRef], lookup: (String) -> (key: String?, title: String)?,
                     attachments: (String, String) -> ArtifactItem?) -> [RefRow] {
        var out: [RefRow] = []
        for (i, ref) in refs.enumerated() {
            let id = "ref\(i)"
            switch ref.kind {
            case .url?:
                guard let url = SafeLink.url(ref.url), let host = url.host else { continue }
                out.append(.link(id: id, title: ref.title ?? host, host: host, url: url))
            case .ticket?:
                guard let t = ref.ticket else { continue }
                if let found = lookup(t) {
                    out.append(.ticket(id: id, label: [found.key, found.title].compactMap { $0 }.joined(separator: " · "), known: true))
                } else {
                    out.append(.ticket(id: id, label: ref.title ?? "Another topic", known: false))
                }
            case .artifact?:
                guard let name = ref.name else { continue }
                out.append(.artifact(id: id, name: name, item: ref.ticket.flatMap { attachments($0, name) }))
            case .file?:
                guard let text = ref.pathText else { continue }
                out.append(.file(id: id, text: text))
            case nil: continue
            }
        }
        return out
    }
}
