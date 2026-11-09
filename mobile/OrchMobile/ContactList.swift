import Foundation

enum ContactList {
    static func chips(_ can: WorkspaceCan?) -> [String] {
        guard let can, !(can.chat && can.tasks && can.files) else { return [] }
        var chips: [String] = []
        if can.chat { chips.append("Chat") }
        if can.tasks { chips.append("Give tasks") }
        if can.files { chips.append("Files") }
        return chips.isEmpty ? ["No access"] : chips
    }

    /// Display names are passed in so filtering stays independent of stored aliases.
    static func rows(_ workspaces: [Workspace], query: String, names: [String: String] = [:]) -> [Workspace] {
        let locale = Locale(identifier: "en_US_POSIX")
        func folded(_ value: String) -> String {
            value.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: locale)
        }
        func name(_ workspace: Workspace) -> String {
            folded(names[workspace.id] ?? workspace.displayName)
        }
        let needle = folded(query.trimmingCharacters(in: .whitespacesAndNewlines))
        return workspaces.filter { needle.isEmpty || name($0).contains(needle) }.sorted {
            let lhs = name($0), rhs = name($1)
            return lhs == rhs ? $0.id < $1.id : lhs < rhs
        }
    }
}
