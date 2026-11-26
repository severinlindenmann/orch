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
                    Section("Earlier days") {
                        switch ChatDay.find(days, query) {
                        case .noHistory:
                            Text("Nothing here yet. Past days of this chat show up here.")
                                .themeFont(15).foregroundStyle(Theme.muted).listRowBackground(Theme.bg)
                        case .noMatch(let term):
                            // The field's own ⓧ clears too; this button keeps one next action in view once the keyboard is gone.
                            VStack(alignment: .leading, spacing: 10) {
                                Text(ChatDay.noMatchText(term))
                                    .themeFont(15).foregroundStyle(Theme.muted)
                                    .accessibilityIdentifier("history-no-match")
                                Button("Clear search") { query = "" }
                                    .buttonStyle(.borderless).themeFont(15, .semibold).foregroundStyle(Theme.brand)
                                    .frame(minHeight: 44).accessibilityIdentifier("history-clear-search")
                            }.listRowBackground(Theme.bg)
                                .onAppear { AccessibilityNotification.Announcement(ChatDay.noMatchText(term)).post() }
                        case .days(let found):
                            ForEach(found.reversed(), id: \.day) { day in
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
                    }
                    Section("Finished groups") {
                        let all = GroupRoomRules.rows(model.groups, closed: true).filter { $0.key.host == workspaceId }
                        let groups = ChatDay.searchTitles(all, query) { $0.title }
                        if all.isEmpty { Text("No finished groups yet.").foregroundStyle(Theme.muted) }
                        else if groups.isEmpty {
                            Text(ChatDay.noGroupMatchText(query.trimmingCharacters(in: .whitespacesAndNewlines)))
                                .themeFont(15).foregroundStyle(Theme.muted).accessibilityIdentifier("history-groups-no-match")
                        }
                        ForEach(groups, id: \.key) { group in
                            NavigationLink { GroupRoomView(key: group.key) } label: {
                                Text("\(group.title) · finished \(ShellTime.day(group.messages.last?.at))")
                            }.accessibilityIdentifier(GroupListRow.rowID(group))
                        }
                    }
                }.listStyle(.plain).scrollContentBackground(.hidden).background(Theme.bg)
                    .accessibilityIdentifier("history-list")
            }
            .foregroundStyle(Theme.text).navigationTitle("Earlier").navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, prompt: "Search earlier messages and groups")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Back to today") { dismiss() } } }
            // A pushed group room links "From ticket ›" / "Open task ›" (and info) by ChatRoute value: this stack needs
            // the same destinations as the chats list, or those links do nothing here.
            .navigationDestination(for: ChatRoute.self) { route in
                switch route {
                case .ticket(let ws, let ticket): TicketChatView(workspaceId: ws, ticketId: ticket)
                case .info(let ws, let ticket):
                    ConversationInfoView(conversation: ticket.map { .topic(workspace: ws, ticket: $0) } ?? .general(workspace: ws))
                case .group(let host, let id): GroupRoomView(key: GroupKey(host: host, id: id))
                default: EmptyView()
                }
            }
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
            Text("\(name)").themeFont(13).foregroundStyle(Theme.muted)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 6)
    }
}
