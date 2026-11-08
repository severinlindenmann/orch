import SwiftUI

struct ChatHistoryView: View {
    let workspaceId: String
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    var body: some View {
        NavigationStack {
            TimelineView(.everyMinute) { context in
                let today = ChatDay.key(for: context.date)
                let days = ChatDay.split(model.conversationItems(.general(workspace: workspaceId)), today: today).past
                List {
                    if days.isEmpty {
                        Text("Nothing here yet. Past days of this chat show up here.")
                            .themeFont(15).foregroundStyle(Theme.muted).listRowBackground(Theme.bg)
                    } else {
                        ForEach(ChatDay.search(days, query).reversed(), id: \.day) { day in
                            NavigationLink {
                                ConversationView(id: .general(workspace: workspaceId), historyDay: day.day, goToToday: { dismiss() })
                            } label: {
                                HStack(spacing: 14) {
                                    Image(systemName: "clock")
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text(ChatDay.label(forDay: day.day, today: today)).themeFont(17, .semibold)
                                        Text("\(day.items.count) \(day.items.count == 1 ? "message" : "messages") · \(day.items.first?.preview ?? "")")
                                            .themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                                    }
                                }.padding(.vertical, 8)
                            }.listRowBackground(Theme.bg).accessibilityIdentifier("history-day-\(day.day)")
                        }
                    }
                }.listStyle(.plain).scrollContentBackground(.hidden).background(Theme.bg)
                    .accessibilityIdentifier("history-list")
            }
            .foregroundStyle(Theme.text).navigationTitle("History").navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, prompt: "Search old chats")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Go to Today") { dismiss() } } }
        }.tint(Theme.brand)
    }
}

struct ChatHelperLabel: View {
    let workspace: Workspace?
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0

    var body: some View {
        let _ = aliasRevision
        let name = workspace.map { WorkspaceAlias.name(for: $0) } ?? "Workspace"
        HStack(spacing: 7) {
            WorkspaceBadge(name: name, icon: workspace?.icon, color: workspace?.color, size: 22)
                .overlay(alignment: .bottomTrailing) {
                    Image(systemName: "sparkle").themeFont(9).foregroundStyle(Theme.brand).offset(x: 3, y: 3)
                }
            Text("\(name) helper").themeFont(13).foregroundStyle(Theme.muted)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 6)
    }
}
