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
    @State private var pendingContact: String?
    @State private var contactQuery = ""
    @State private var showSettings = false
    @Environment(\.dynamicTypeSize) private var typeSize
    // Concatenated Text can't take themeFont: these follow Dynamic Type live (ScaledMetric reads the environment).
    @ScaledMetric private var questionKeySize: CGFloat = 13
    @ScaledMetric private var questionTitleSize: CGFloat = 17
    private let filters = ["All", "Unread", "Needs your OK"]

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
                    MuteAllBanner()
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
                    case .groupHistory: GroupHistoryView()
                    case .newChat: NewTopicScreen(workspaceId: nil)
                    case .newTopic(let ws): NewTopicScreen(workspaceId: ws)
                    }
                }.toolbar({ if case .group = route { return Visibility.hidden }; return Visibility.visible }(), for: .navigationBar)
            }
            .sheet(item: $sheet, onDismiss: {
                if let id = pendingContact { pendingContact = nil; model.path.append(ChatRoute.general(id)) }
                if let next = pendingSheet { pendingSheet = nil; sheet = next }
            }) { item in
                switch item {
                case .compose:
                    composeSheet.presentationDetents([.large]).presentationDragIndicator(.visible)
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
            Button { contactQuery = ""; sheet = .compose } label: {
                Image(systemName: "plus").themeFont(22).foregroundStyle(Theme.brand)
                    .frame(width: 44, height: 44).background(Theme.surface, in: Circle())
            }.accessibilityIdentifier("new-chat").accessibilityLabel("New chat")
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
                }.buttonStyle(PressStyle()).accessibilityIdentifier("filter-\(option == "Needs your OK" ? "Needs you" : option)")
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
                Image(systemName: "bubble.left").themeFont(32).foregroundStyle(Theme.brand)
                    .frame(width: 70, height: 70).background(Theme.surface, in: RoundedRectangle(cornerRadius: 24))
                Text("No chats yet").themeFont(20, .semibold)
                Button("Add a workspace") { sheet = .addWorkspace }.buttonStyle(PrimaryButtonStyle())
            }.frame(maxWidth: .infinity).padding(.vertical, 50).accessibilityIdentifier("chats-empty")
        } else {
            attentionCards
            let shown = model.workspaceSummaries.filter { ChatsRowRules.matches(filter, unread: $0.unread, needsYou: $0.openQuestions > 0) }
            let groupsShown = GroupsSection.shown(model, filter: filter)
            if shown.isEmpty && groupsShown.isEmpty {
                Text("Nothing here yet.").themeFont(15).foregroundStyle(Theme.muted).padding(.vertical, 24)
            } else if !shown.isEmpty {
                VStack(spacing: 0) {
                    ForEach(shown) { summary in
                        workspaceRow(summary)
                        if summary.id != shown.last?.id { ShellDivider().padding(.leading, 64) }
                    }
                }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            }
            GroupsSection(filter: filter, groups: groupsShown)
            if model.archivedCount > 0 && filter == "All" { archivedRow }
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
        let questions = ChatsRowRules.needsYou(model.questions, answers: model.answers)
        if !questions.isEmpty && (filter == "All" || filter == "Needs your OK") {
            // Pinned: at most three, the rest behind "See all (n)" (the Needs your OK filter lists them all).
            let pinned = filter == "All" ? ChatsRowRules.pinned(questions) : questions
            VStack(alignment: .leading, spacing: 10) {
                Text("Needs your OK · \(questions.count)").themeFont(13, .semibold).foregroundStyle(Theme.warn)
                    .accessibilityAddTraits(.isHeader)
                VStack(spacing: 0) {
                    ForEach(pinned) { question in
                        let ws = question.message.from
                        let summary = model.workspaceSummaries.first { $0.id == ws }
                        let wsName = summary.map { WorkspaceAlias.name(for: $0.workspace) } ?? question.workspaceName
                        let topic = summary?.topics.first { $0.id.ticket == question.message.ticket && question.message.ticket != nil }
                        let title = topic?.title ?? question.message.body.title ?? (question.message.ticket == nil ? "Your helper" : wsName)
                        NavigationLink(value: question.message.ticket.map { ChatRoute.ticket(workspace: ws, ticket: $0) } ?? .workspace(ws)) {
                            HStack(spacing: 12) {
                                WorkspaceBadge(name: wsName, icon: summary?.workspace.icon, color: summary?.workspace.color, size: 32)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(title).font(.system(size: questionTitleSize, weight: .semibold)).foregroundColor(Theme.text)
                                        .lineLimit(ChatsRowRules.titleLines(typeSize.isAccessibilitySize))
                                    Text([wsName, ShellTime.day(question.message.createdAt)].filter { !$0.isEmpty }.joined(separator: " · "))
                                        .themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                                    Text(question.message.body.text).themeFont(13).foregroundStyle(Theme.muted).lineLimit(2)
                                }.frame(maxWidth: .infinity, alignment: .leading).multilineTextAlignment(.leading)
                                ShellChevron()
                            }.padding(.horizontal, 16).padding(.vertical, 14).contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text)
                            .accessibilityIdentifier("needs-you-\(question.id)")
                        if question.id != pinned.last?.id { ShellDivider() }
                    }
                    if pinned.count < questions.count {
                        ShellDivider()
                        Button { filter = "Needs your OK" } label: {
                            HStack {
                                Text("See all (\(questions.count))").themeFont(15, .semibold)
                                Spacer()
                                ShellChevron()
                            }.frame(minHeight: 44).padding(.horizontal, 16).padding(.vertical, 4).contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("needs-you-see-all")
                    }
                }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            }
        }
    }

    private func workspaceRow(_ summary: WorkspaceSummary) -> some View {
        let name = WorkspaceAlias.name(for: summary.workspace)
        let newest = summary.topics.max { ($0.lastAt ?? "") < ($1.lastAt ?? "") }
        let starting = newest?.isStarting == true && newest?.lastAt == summary.lastAt
        let working = ChatsRowRules.isWorking(summary.topics)
        let preview = ChatsRowRules.preview(summary.lastLine, starting: starting, working: working, unread: summary.unread)
        return TimelineView(.everyMinute) { context in
            let muted = model.notificationsMuted(workspace: summary.id, now: context.date)
            NavigationLink(value: ChatRoute.workspace(summary.id)) {
                HStack(spacing: 12) {
                    WorkspaceBadge(name: name, icon: summary.workspace.icon, color: summary.workspace.color, size: 46, lastSeen: .some(summary.workspace.lastSeen), id: summary.id)
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(name).themeFont(17, .semibold).lineLimit(ChatsRowRules.titleLines(typeSize.isAccessibilitySize))
                            if muted { MutedIcon() }
                        }
                        HStack(spacing: 6) {
                            if working && !starting { ProgressView().controlSize(.mini).tint(Theme.muted).accessibilityHidden(true) }
                            Text(preview).themeFont(15).foregroundStyle(Theme.muted).lineLimit(1)
                        }
                        if let label = ChatsRowRules.questionLabel(summary.openQuestions) {
                            Text(label).themeFont(13).foregroundStyle(Theme.warn).accessibilityLabel(ChatsRowRules.needsYouSpoken(summary.openQuestions) ?? label)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .trailing, spacing: 10) {
                        Text(ShellTime.short(summary.lastAt)).themeFont(12).foregroundStyle(Theme.muted).lineLimit(1).minimumScaleFactor(0.8)
                        ShellBadge(count: summary.unread, muted: muted)
                    }
                    ShellChevron()
                }.padding(.horizontal, 12).padding(.vertical, 14).contentShape(Rectangle())
            }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("room-\(summary.id)")
                .contextMenu {
                    MuteMenu(muted: summary.workspace.isMuted(now: context.date)) { mute in
                        Task { await model.setMute(summary.id, mute) }
                    }
                }
        }
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
                            Text(row.ticket.displayTitle).themeFont(16, .semibold)
                            Text([ShellTime.day(row.ticket.at), row.ticket.workspaceName, row.ticket.stateLine].filter { !$0.isEmpty }.joined(separator: " · ")).themeFont(13).foregroundStyle(Theme.muted)
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
        let names = Dictionary(model.workspaces.map { ($0.id, WorkspaceAlias.name(for: $0)) }, uniquingKeysWith: { first, _ in first }) // relay data: never trap on a duplicate id
        let contacts = ContactList.rows(model.workspaces, query: contactQuery, names: names)
        return VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("New chat").themeFont(22, .bold).accessibilityAddTraits(.isHeader)
                Spacer()
                Button { sheet = nil } label: {
                    Image(systemName: "xmark").themeFont(20)
                        .frame(width: 44, height: 44).background(Theme.surface3, in: Circle())
                }.buttonStyle(PressStyle()).accessibilityLabel("Close").accessibilityIdentifier("new-chat-close")
            }
            HStack(spacing: 12) {
                Image(systemName: "magnifyingglass").foregroundStyle(Theme.muted).accessibilityHidden(true)
                TextField("Search contacts", text: $contactQuery).themeFont(17)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityIdentifier("contact-search")
            }.padding(.horizontal, 14).frame(minHeight: 44)
                .background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.border, lineWidth: 1))
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    composeOption("New topic", symbol: "square.and.pencil", target: .newTopic, identifier: "compose-new-topic")
                    ShellDivider()
                    composeOption("Add workspace", symbol: "plus", target: .addWorkspace, identifier: "compose-add-workspace")
                    Text("Contacts").themeFont(14, .semibold).foregroundStyle(Theme.muted)
                        .accessibilityAddTraits(.isHeader).padding(.top, 24).padding(.bottom, 12)
                    if contacts.isEmpty {
                        Text(model.workspaces.isEmpty ? "No contacts yet" : "No match")
                            .themeFont(15).foregroundStyle(Theme.muted).padding(.vertical, 16)
                    }
                    ForEach(contacts) { workspace in
                        contactRow(workspace, name: names[workspace.id] ?? workspace.displayName)
                        ShellDivider()
                    }
                }
            }.scrollDismissesKeyboard(.interactively)
        }.padding(16).padding(.top, 12).foregroundStyle(Theme.text)
            .accessibilityElement(children: .contain).accessibilityIdentifier("new-chat-sheet")
    }

    private func contactRow(_ workspace: Workspace, name: String) -> some View {
        let chips = ContactList.chips(workspace.can)
        return Button { pendingContact = workspace.id; sheet = nil } label: {
            HStack(spacing: 12) {
                WorkspaceBadge(name: name, icon: workspace.icon, color: workspace.color, size: 46,
                               lastSeen: .some(workspace.lastSeen), id: workspace.id)
                VStack(alignment: .leading, spacing: 4) {
                    Text(name).themeFont(17, .semibold).multilineTextAlignment(.leading)
                    TimelineView(.everyMinute) { context in
                        Text(workspace.presence(now: context.date).line(now: context.date))
                            .themeFont(13).foregroundStyle(Theme.muted)
                    }
                    if !chips.isEmpty {
                        HStack(spacing: 6) {
                            ForEach(chips, id: \.self) { chip in
                                Text(chip).themeFont(12).foregroundStyle(Theme.muted)
                                    .padding(.horizontal, 8).padding(.vertical, 3)
                                    .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
                            }
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
                ShellChevron()
            }.frame(minHeight: 56).padding(.vertical, 12).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityIdentifier("contact-\(workspace.id)")
    }

    private func composeOption(_ title: String, symbol: String, target: ShellSheet, identifier: String) -> some View {
        Button { pendingSheet = target; sheet = nil } label: {
            HStack(spacing: 12) {
                Image(systemName: symbol).themeFont(20).foregroundStyle(Theme.brand)
                    .frame(width: 46, height: 46)
                    .background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                    .accessibilityHidden(true)
                Text(title).themeFont(17, .semibold)
                Spacer()
                ShellChevron()
            }.frame(minHeight: 56).padding(.vertical, 8).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityIdentifier(identifier)
    }
}


/// Chat list numbers, one meaning each: the row badge is unread messages (`WorkspaceSummary.unread`), the row's
/// "1 question" line is open questions (`openQuestions`), "Needs your OK · N" is conversations with an open question.
enum ChatsRowRules {
    /// Questions still waiting for an answer (not reviews, not "make a ticket" offers).
    static func openQuestions(_ questions: [Question], answers: [String: String], workspace: String? = nil) -> [Question] {
        questions.filter { !$0.isReview && !$0.isMakeTicket && answers[$0.id] == nil && (workspace == nil || $0.message.from == workspace) }
    }
    /// One entry per conversation (General or topic) with an open question: the oldest open question there.
    static func needsYou(_ questions: [Question], answers: [String: String]) -> [Question] {
        var seen = Set<String>()
        return openQuestions(questions, answers: answers)
            .sorted { $0.message.createdAt < $1.message.createdAt }
            .filter { seen.insert($0.message.from + "|" + ($0.message.ticket ?? "")).inserted }
    }
    static let pinnedLimit = 3
    /// The pinned "Needs your OK" section shows at most three; the rest sit behind "See all (n)".
    static func pinned(_ questions: [Question]) -> [Question] { Array(questions.prefix(pinnedLimit)) }
    /// Row titles: one line (tail cut) at default sizes, two at accessibility Dynamic Type sizes. Full title: Info.
    static func titleLines(_ accessibilitySize: Bool) -> Int { accessibilitySize ? 2 : 1 }
    /// Chat headers drop their subtitle (status, last seen) at accessibility sizes so the title stays readable; Info has it.
    static func showsHeaderSubtitle(_ accessibilitySize: Bool) -> Bool { !accessibilitySize }
    /// VoiceOver words for the amber needs-you count, kept apart from the unread badge ("3 unread").
    static func needsYouSpoken(_ count: Int) -> String? { count > 0 ? (count == 1 ? "1 question needs your OK" : "\(count) questions need your OK") : nil }
    /// One filter rule for every conversation kind on the list (workspaces and groups).
    static func matches(_ filter: String, unread: Int, needsYou: Bool) -> Bool {
        switch filter { case "Unread": unread > 0; case "Needs your OK": needsYou; default: true }
    }
    /// The helper is busy on a topic (a "Working…" subtitle, like "typing…").
    static func isWorking(_ topics: [TopicSummary]) -> Bool {
        topics.contains { $0.status == .working && !$0.isStarting }
    }
    /// "1 question", "3 questions"; nil when none.
    static func questionLabel(_ count: Int) -> String? {
        count > 0 ? (count == 1 ? "1 question" : "\(count) questions") : nil
    }
    /// An unread reply wins over "Working…" (the spinner still shows the helper is busy).
    static func preview(_ text: String, starting: Bool = false, working: Bool = false, unread: Int = 0) -> String {
        if starting { return "Getting started…" }
        if working && unread == 0 { return "Working…" }
        return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "No messages yet" : text
    }
}
