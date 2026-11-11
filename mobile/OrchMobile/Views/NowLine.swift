import SwiftUI

struct NowLine: View {
    let running: Int
    let newCount: Int
    var newFrom: String? = nil
    var scoped = false

    static func text(running: Int, newCount: Int, newFrom: String?) -> String? {
        let fresh = newCount > 0 ? newFrom.map { "\(newCount) new from \($0)" } : nil
        return joined(running: running, fresh: fresh)
    }

    static func scopedText(running: Int, newCount: Int) -> String? {
        joined(running: running, fresh: newCount > 0 ? "\(newCount) new" : nil)
    }

    private static func joined(running: Int, fresh: String?) -> String? {
        let parts = [running > 0 ? "Working on \(running) tickets" : nil, fresh].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    static func counts(_ summaries: [WorkspaceSummary]) -> (running: Int, newCount: Int, newFrom: String?) {
        let running = summaries.reduce(0) { count, summary in
            count + summary.topics.filter { $0.status == .working && !$0.isStarting }.count
        }
        let newest = summaries.filter { $0.unread > 0 }.max { $0.unread < $1.unread }
        return (running, newest?.unread ?? 0, newest.map { WorkspaceAlias.name(for: $0.workspace) })
    }

    var body: some View {
        if let text = scoped ? Self.scopedText(running: running, newCount: newCount)
            : Self.text(running: running, newCount: newCount, newFrom: newFrom) {
            HStack(spacing: 10) {
                Text(text).themeFont(15).foregroundStyle(Theme.text)
                Spacer(minLength: 0)
                if newCount > 0 && (scoped || newFrom != nil) {
                    Text("NEW").themeFont(11, .bold).foregroundStyle(Theme.warn)
                        .padding(.horizontal, 4).padding(.vertical, 2)
                        .background(Theme.warn.opacity(0.18), in: RoundedRectangle(cornerRadius: 3))
                }
            }.padding(.horizontal, 12).padding(.vertical, 14)
        }
    }
}
