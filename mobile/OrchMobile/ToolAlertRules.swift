import Foundation

/// The tool warnings a workspace view shows (contracts/tool-alert.md; vectors/tool-alert-v1.json `phone`). Pure rules.
enum ToolAlertRules {
    struct Row: Equatable, Identifiable, Sendable {
        let workspaceId: String
        let name: String
        let text: String
        /// "bad" = stopped working or cannot be reached, "warn" = runs out soon.
        let tone: String
        let at: String
        var id: String { "\(workspaceId)|\(name)" }
    }

    /// One row per (workspace, name) whose newest valid warning is not `works`, newest first. Only workspace texts
    /// count (a phone cannot send one); a malformed warning is ignored.
    static func rows(_ messages: [PhoneMessage], workspaceId: String? = nil) -> [Row] {
        var newest: [String: (PhoneMessage, ToolAlert)] = [:]
        for m in messages where !m.fromPhone {
            guard let a = m.message.body.toolAlert else { continue }
            if let ws = workspaceId, m.message.from != ws { continue }
            let key = "\(m.message.from)|\(a.name)"
            if let have = newest[key], have.0.message.createdAt >= m.message.createdAt { continue }
            newest[key] = (m, a)
        }
        return newest.values
            .filter { $0.1.state != "works" }
            .sorted { $0.0.message.createdAt > $1.0.message.createdAt }
            .map { m, a in
                Row(workspaceId: m.message.from, name: a.name, text: m.message.body.text,
                    tone: a.state == "soon" ? "warn" : "bad", at: m.message.createdAt)
            }
    }
}
