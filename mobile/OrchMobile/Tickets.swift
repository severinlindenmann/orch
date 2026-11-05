import Foundation

/// "Your tickets": what the phone shows instead of a list of workspaces. Built from the updates feed
/// (`GET /v1/phone/updates`) plus the open questions, no second store.
struct Ticket: Identifiable, Equatable, Sendable {
    enum Status: Int, Comparable, Sendable {
        case needsYou, working, done
        static func < (a: Status, b: Status) -> Bool { a.rawValue < b.rawValue }
        var title: String { switch self { case .needsYou: "Needs you"; case .working: "Working on"; case .done: "Done" } }
    }
    let id: String
    let workspace: String
    let workspaceName: String
    let ticket: String?
    let title: String
    /// The newest line the workspace wrote about it ("where things stand").
    let text: String
    let status: Status
    /// failure and stopped are "Done" but get a different sign.
    let kind: String
    let at: String
    let question: Question?

    /// One plain line under the title, from the update kind.
    var stateLine: String {
        let first = text.split(separator: " ").prefix(6).joined(separator: " ")
        switch status {
        case .needsYou: return "Waiting for your answer"
        case .working: return "Working on it"
        case .done:
            switch kind {
            case "failure": return first.isEmpty ? "Did not work" : "Did not work — \(first)"
            case "stopped": return "Stopped"
            default: return first.isEmpty ? "Done" : "Done — \(first)"
            }
        }
    }

    var symbol: String {
        switch status {
        case .needsYou: "exclamationmark.circle.fill"
        case .working: "circle.dotted"
        case .done: kind == "result" ? "checkmark.circle.fill" : "xmark.circle.fill"
        }
    }
}

enum TicketBuilder {
    static func status(forKind kind: String) -> Ticket.Status {
        switch kind {
        case "question": .needsYou
        case "result", "failure", "stopped": .done
        default: .working   // ack, working, note
        }
    }

    /// Open questions win: a ticket with an unanswered question is "Needs you" whatever its last update said.
    static func build(updates: [TicketUpdate], questions: [Question], answers: [String: String]) -> [Ticket] {
        var byKey: [String: Ticket] = [:]
        for u in updates {
            let key = "\(u.workspace)|\(u.ticket)"
            var st = status(forKind: u.kind)
            if st == .needsYou { st = .working }   // only a real open question counts (below)
            byKey[key] = Ticket(id: key, workspace: u.workspace, workspaceName: u.workspaceName, ticket: u.ticket,
                                title: u.title ?? u.text, text: u.text, status: st, kind: u.kind, at: u.at, question: nil)
        }
        for q in questions where answers[q.id] == nil {
            let m = q.message
            let key = m.ticket.map { "\(m.from)|\($0)" } ?? "q|\(q.id)"
            let old = byKey[key]
            byKey[key] = Ticket(id: key, workspace: m.from, workspaceName: q.workspaceName, ticket: m.ticket,
                                title: m.body.title ?? old?.title ?? m.body.text, text: m.body.text, status: .needsYou,
                                kind: "question", at: m.createdAt, question: q)
        }
        return byKey.values.sorted { ($0.status, $1.at) < ($1.status, $0.at) }
    }
}
