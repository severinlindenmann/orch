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
                    }
                    Section("Finished groups") {
                        let groups = GroupRoomRules.rows(model.groups, closed: true).filter { $0.key.host == workspaceId }
                        if groups.isEmpty { Text("No finished groups yet.").foregroundStyle(Theme.muted) }
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
            .searchable(text: $query, prompt: "Search old chats")
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
