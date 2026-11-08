import SwiftUI

private enum ShellSheet: String, Identifiable {
    case compose, newTopic, addWorkspace
    var id: String { rawValue }
}

struct ChatsListView: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    @Environment(AppModel.self) private var model
    @State private var query = ""
    @State private var filter = "All"
    @State private var sheet: ShellSheet?
    @State private var pendingSheet: ShellSheet?
    @State private var showSettings = false
    private let filters = ["All", "Unread", "Needs you"]

    var body: some View {
        let _ = aliasRevision
        @Bindable var model = model
        NavigationStack(path: $model.path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    header
                    ModelMessage()
                    searchField
                    chips
                    content
                }.padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 24)
            }
            .background(Theme.bg.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await model.refresh() }
            // `-startTab settings` (tests, screenshots) and old callers that set `model.tab = .settings`.
            .task(id: model.tab) { if model.tab == .settings { model.tab = .chats; showSettings = true } }
            .navigationDestination(isPresented: $showSettings) { SettingsView().toolbar(.visible, for: .navigationBar) }
            .navigationDestination(for: ChatRoute.self) { route in
                Group {
                    switch route {
                    case .workspace(let id): WorkspaceView(workspaceId: id)
                    case .general(let id): ChatRoomView(workspaceId: id)
                    case .ticket(let ws, let ticket): TicketChatView(workspaceId: ws, ticketId: ticket)
                    case .info(let ws, let ticket):
                        ConversationInfoView(conversation: ticket.map { .topic(workspace: ws, ticket: $0) } ?? .general(workspace: ws))
                    case .group(let host, let id): GroupRoomView(key: GroupKey(host: host, id: id))
                    case .newChat: NewTopicScreen(workspaceId: nil)
                    case .newTopic(let ws): NewTopicScreen(workspaceId: ws)
                    }
                }.toolbar({ if case .group = route { return Visibility.hidden }; return Visibility.visible }(), for: .navigationBar)
            }
            .sheet(item: $sheet, onDismiss: {
                if let next = pendingSheet { pendingSheet = nil; sheet = next }
            }) { item in
                switch item {
                case .compose:
                    composeSheet.presentationDetents([.height(220), .medium]).presentationDragIndicator(.visible)
                        .presentationBackground(Theme.surface)
                case .newTopic:
                    NewTopicScreen(workspaceId: nil, asSheet: true).presentationDetents([.medium, .large])
                case .addWorkspace:
                    AddWorkspaceView().presentationDetents([.medium, .large])
                }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            NavigationLink { SettingsView().toolbar(.visible, for: .navigationBar) } label: {
                Image(systemName: "gearshape").themeFont(20).foregroundStyle(Theme.brand)
                    .frame(width: 44, height: 44).background(Theme.surface, in: Circle())
            }.accessibilityIdentifier("settings-button").accessibilityLabel("Settings")
            Text("Chats").themeFont(34, .bold).accessibilityAddTraits(.isHeader)
            Spacer(minLength: 0)
            Button { sheet = .compose } label: {
                Image(systemName: "plus").themeFont(22).foregroundStyle(Theme.brand)
                    .frame(width: 44, height: 44).background(Theme.surface, in: Circle())
            }.accessibilityIdentifier("new-chat").accessibilityLabel("New")
        }.buttonStyle(PressStyle())
    }

    private var searchField: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").foregroundStyle(Theme.muted).accessibilityHidden(true)
            TextField("Search chats and messages", text: $query).themeFont(15)
                .textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("chat-search")
            if !query.isEmpty {
                Button { query = "" } label: { Image(systemName: "xmark.circle.fill").frame(width: 44, height: 44) }
                    .foregroundStyle(Theme.muted).accessibilityLabel("Clear search")
            }
        }.padding(.horizontal, 14).frame(minHeight: 44).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
    }

    private var chips: some View {
        HStack(spacing: 0) {
            ForEach(filters, id: \.self) { option in
                Button { filter = option } label: {
                    Text(option).themeFont(13).lineLimit(2).minimumScaleFactor(0.8)
                        .foregroundStyle(filter == option ? Theme.text : Theme.muted)
                        .frame(maxWidth: .infinity, minHeight: 44).padding(.vertical, 2)
                        .background(filter == option ? Theme.surface3 : .clear, in: RoundedRectangle(cornerRadius: Theme.Radius.m - 4, style: .continuous))
                }.buttonStyle(PressStyle()).accessibilityIdentifier("filter-\(option)")
                    .accessibilityAddTraits(filter == option ? .isSelected : [])
            }
        }.padding(4).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
    }

    @ViewBuilder private var content: some View {
        if !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            searchResults(ChatBuilder.search(query, model.chatData, rows: model.chatRooms))
        } else if !model.hasLoaded && model.message == nil {
            VStack(spacing: 0) {
                ForEach(0..<3, id: \.self) { _ in
                    HStack(spacing: 12) {
                        WorkspaceBadge(name: "Workspace")
                        VStack(alignment: .leading) { Text("Workspace name").themeFont(17, .semibold); Text("Latest message in this workspace").themeFont(15) }
                    }.padding(16)
                }
            }.frame(maxWidth: .infinity, alignment: .leading).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                .skeleton(true).accessibilityHidden(true)
        } else if model.workspaceSummaries.isEmpty {
            VStack(spacing: 14) {
                OrbitMark().frame(width: 48, height: 48)
                Text("No workspaces yet").themeFont(20, .semibold)
                Text("Add a workspace with the invitation you were sent.").themeFont(15).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
                Button("Add workspace") { sheet = .addWorkspace }.buttonStyle(SecondaryButtonStyle())
            }.frame(maxWidth: .infinity).padding(.vertical, 50).accessibilityIdentifier("chats-empty")
        } else {
            attentionCards
            let now = NowLine.counts(model.workspaceSummaries)
            NowLine(running: now.running, newCount: now.newCount, newFrom: now.newFrom)
            let shown = model.workspaceSummaries.filter { filter == "All" || (filter == "Unread" ? $0.unread > 0 : $0.openQuestions > 0) }
            if shown.isEmpty {
                Text("Nothing here yet.").themeFont(15).foregroundStyle(Theme.muted).padding(.vertical, 24)
            } else {
                VStack(spacing: 0) {
                    ForEach(shown) { summary in
                        workspaceRow(summary)
                        if summary.id != shown.last?.id { ShellDivider().padding(.leading, 64) }
                    }
                }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            }
            GroupsSection()
            if model.archivedCount > 0 { archivedRow }
        }
    }

    /// "Archived" at the end of the list (all workspaces, grouped per workspace).
    private var archivedRow: some View {
        NavigationLink { ArchivedView(workspaceId: nil) } label: {
            HStack(spacing: 12) {
                Image(systemName: "archivebox").themeFont(20).foregroundStyle(Theme.muted).frame(width: 24).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Archived").themeFont(17, .semibold)
                    Text("\(model.archivedCount) chat\(model.archivedCount == 1 ? "" : "s")").themeFont(13).foregroundStyle(Theme.muted)
                }
                Spacer()
                ShellChevron()
            }.frame(minHeight: 44).padding(.horizontal, 16).padding(.vertical, 12).contentShape(Rectangle())
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("archived-row-all").padding(.top, 6)
            .accessibilityLabel("Archived").accessibilityValue("\(model.archivedCount) chat\(model.archivedCount == 1 ? "" : "s")")
    }

    @ViewBuilder private var attentionCards: some View {
        let questions = model.questions.filter { model.answers[$0.id] == nil }
        if !questions.isEmpty && (filter == "All" || filter == "Needs you") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Needs you · \(questions.count)").themeFont(13, .semibold).foregroundStyle(Theme.warn)
                    .accessibilityAddTraits(.isHeader)
                VStack(spacing: 0) {
                    ForEach(questions) { question in
                        let ws = question.message.from
                        let summary = model.workspaceSummaries.first { $0.id == ws }
                        let topic = summary?.topics.first { $0.id.ticket == question.message.ticket && question.message.ticket != nil }
                        let key = topic?.key ?? question.message.key
                        let title = topic?.title ?? question.message.body.title ?? summary.map { WorkspaceAlias.name(for: $0.workspace) } ?? question.workspaceName
                        NavigationLink(value: question.message.ticket.map { ChatRoute.ticket(workspace: ws, ticket: $0) } ?? .workspace(ws)) {
                            HStack(spacing: 14) {
                                Image(systemName: "bubble.left").themeFont(20).foregroundStyle(Theme.warn).accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("\(key.map { "\($0) " } ?? "")")
                                        .font(Theme.font(13)).foregroundColor(Theme.muted)
                                    + Text(title).font(Theme.font(17, .semibold)).foregroundColor(Theme.text)
                                    Text(question.message.body.text).themeFont(13).foregroundStyle(Theme.muted).lineLimit(2)
                                }.frame(maxWidth: .infinity, alignment: .leading).multilineTextAlignment(.leading)
                                ShellChevron()
                            }.padding(.horizontal, 16).padding(.vertical, 14).contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text)
                        if question.id != questions.last?.id { ShellDivider() }
                    }
                }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            }
        }
    }

    private func workspaceRow(_ summary: WorkspaceSummary) -> some View {
        let name = WorkspaceAlias.name(for: summary.workspace)
        let newest = summary.topics.max { ($0.lastAt ?? "") < ($1.lastAt ?? "") }
        let starting = newest?.isStarting == true && newest?.lastAt == summary.lastAt
        return NavigationLink(value: ChatRoute.workspace(summary.id)) {
            HStack(spacing: 12) {
                WorkspaceBadge(name: name, icon: summary.workspace.icon, color: summary.workspace.color, size: 46, lastSeen: .some(summary.workspace.lastSeen), id: summary.id)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Chat · \(name)").themeFont(17, .semibold).lineLimit(2)
                    Text(starting ? "Getting started…" : summary.lastLine).themeFont(15).foregroundStyle(Theme.muted).lineLimit(1)
                    if summary.openQuestions > 0 { Text(summary.openQuestions == 1 ? "1 needs you" : "\(summary.openQuestions) need you").themeFont(13).foregroundStyle(Theme.warn) }
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .trailing, spacing: 10) {
                    Text(ShellTime.short(summary.lastAt)).themeFont(12).foregroundStyle(Theme.muted).lineLimit(1).minimumScaleFactor(0.8)
                    ShellBadge(count: summary.unread)
                    if summary.isMuted { Image(systemName: "bell.slash").themeFont(12).foregroundStyle(Theme.muted).accessibilityLabel("Muted") }
                }
                ShellChevron()
            }.padding(.horizontal, 12).padding(.vertical, 14).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("room-\(summary.id)")
    }

    @ViewBuilder private func searchResults(_ result: ChatSearchResult) -> some View {
        if result.isEmpty { Text("No match on this phone.").themeFont(14).foregroundStyle(Theme.muted).padding(.top, 20) }
        if !result.rooms.isEmpty {
            Eyebrow(text: "Workspaces")
            ForEach(result.rooms) { row in
                if let summary = model.workspaceSummaries.first(where: { $0.id == row.id }) { workspaceRow(summary) }
            }
        }
        if !result.chats.isEmpty {
            Eyebrow(text: "Topics")
            ForEach(result.chats) { row in
                NavigationLink(value: ChatRoute.ticket(workspace: row.ticket.workspace, ticket: row.ticket.ticket ?? "")) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text([row.ticket.key, row.ticket.displayTitle].compactMap { $0 }.joined(separator: " · ")).themeFont(16, .semibold)
                            Text(row.ticket.workspaceName + " · " + row.ticket.stateLine).themeFont(13).foregroundStyle(Theme.muted)
                        }
                        Spacer(); ShellBadge(count: row.unread); ShellChevron()
                    }.orchCard()
                }.buttonStyle(PressStyle()).foregroundStyle(Theme.text)
                    .accessibilityIdentifier("ticket-\(row.ticket.workspace)|\(row.ticket.ticket ?? "")")
            }
        }
        if !result.messages.isEmpty {
            Eyebrow(text: "Messages")
            ForEach(result.messages) { hit in
                NavigationLink(value: hit.route) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(hit.who).themeFont(12, .semibold).foregroundStyle(Theme.brand)
                        Text(hit.text).themeFont(14).lineLimit(2)
                    }.orchCard()
                }.buttonStyle(PressStyle()).foregroundStyle(Theme.text)
            }
        }
    }

    private var composeSheet: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Compose").themeFont(20, .semibold).padding(.bottom, 8)
            composeOption("New topic", symbol: "square.and.pencil", target: .newTopic, identifier: "compose-new-topic")
            ShellDivider()
            composeOption("Add workspace", symbol: "plus", target: .addWorkspace, identifier: "compose-add-workspace")
        }.padding(24).foregroundStyle(Theme.text)
    }

    private func composeOption(_ title: String, symbol: String, target: ShellSheet, identifier: String) -> some View {
        Button { pendingSheet = target; sheet = nil } label: {
            HStack { Label(title, systemImage: symbol); Spacer(); ShellChevron() }
                .themeFont(17).frame(minHeight: 44).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityIdentifier(identifier)
    }
}
