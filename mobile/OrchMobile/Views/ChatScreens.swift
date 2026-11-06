import SwiftUI

struct ConversationHooks {
    var composer = ComposerHooks.none
    var openArtifact: (String) -> Void = { _ in }
    static var none: ConversationHooks { ConversationHooks() }
}

struct ChatRoomView: View {
    let workspaceId: String
    var body: some View { ConversationView(id: .general(workspace: workspaceId)) }
}

struct TicketChatView: View {
    let workspaceId: String
    let ticketId: String
    var body: some View { ConversationView(id: .topic(workspace: workspaceId, ticket: ticketId)) }
}

struct ConversationView: View {
    let id: ConversationID
    var hooks = ConversationHooks.none
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var reply: ReplyPreview?
    @State private var tasksShown = false
    @State private var atBottom = true
    @State private var loaded = false
    @State private var scrolledQuestion: String?
    @State private var seenIncoming: Set<String> = []
    private var resolved: ConversationID { model.resolve(id) }
    private var items: [ConvItem] { model.conversationItems(resolved) }
    private var workspaceName: String { model.workspace(resolved.workspace)?.name ?? "Workspace" }
    private var ticket: Ticket? { model.tickets.first { $0.workspace == resolved.workspace && $0.ticket == resolved.ticket && resolved.ticket != nil } }
    private var title: String {
        switch resolved {
        case .general: workspaceName
        case .starting: "New topic"
        case .topic: ticket.map { [$0.key, $0.displayTitle].compactMap { $0 }.joined(separator: " · ") } ?? "Topic"
        }
    }
    private var working: Bool {
        if let ticket { return TopicStatus(ticket) == .working }
        if case .general = resolved { return items.last?.side == .me && items.last?.receipt == .started }
        return false
    }
    private var unread: Int { items.filter { $0.incoming && !seenIncoming.contains($0.id) }.count }

    var body: some View {
        VStack(spacing: 0) {
            if model.speech.isActive { MiniPlayer() }
            OfflineBanner()
            if let ticket { summary(ticket) }
            messages
        }.background(Theme.bg).foregroundStyle(Theme.text)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(title).themeFont(16, .semibold).lineLimit(1).accessibilityIdentifier("chat-title")
                        presence
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink(value: ChatRoute.info(workspace: resolved.workspace, ticket: resolved.ticket)) {
                        Image(systemName: "info.circle").themeFont(18).frame(minWidth: 44, minHeight: 44)
                    }.accessibilityLabel("Chat info").accessibilityIdentifier("chat-info")
                }
            }
            .navigationBarTitleDisplayMode(.inline).toolbarColorScheme(.dark, for: .navigationBar)
            .toolbarBackground(Theme.surface, for: .navigationBar).toolbarBackground(.visible, for: .navigationBar)
            .tint(Theme.brand)
            .safeAreaInset(edge: .bottom, spacing: 0) {
                VStack(spacing: 0) {
                    if working { StatusLine("\(workspaceName) is working…") }
                    Composer(target: resolved.target, note: ticket.map { ChatBuilder.composerNote(running: $0.view?.running) }, reply: $reply, hooks: hooks.composer)
                }
            }
            .sheet(isPresented: $tasksShown) { tasksSheet }
            .accessibilityIdentifier("conversation-view")
    }
    @ViewBuilder private var presence: some View {
        if case .starting = resolved { Text("Starting topic…").themeFont(13).foregroundStyle(Theme.muted) }
        else {
            HStack(spacing: 4) {
                if resolved.ticket != nil { Text("\(workspaceName) ·") }
                if model.presence(of: resolved.workspace).isOnline { PresenceDot() }
                Text(model.presence(of: resolved.workspace).text().lowercased())
            }.themeFont(13).foregroundStyle(Theme.muted)
        }
    }
    private func summary(_ ticket: Ticket) -> some View {
        Button { tasksShown = true } label: {
            HStack {
                Text("\(ticket.view?.doneCount ?? 0) of \(ticket.view?.totalCount ?? 0) · \(TopicStatus(ticket).label)")
                Spacer(minLength: 8)
                Image(systemName: "chevron.down")
            }.themeFont(13).foregroundStyle(Theme.muted).padding(.horizontal, 18).frame(minHeight: 44)
                .background(Theme.surface).overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
        }.buttonStyle(PressStyle()).accessibilityLabel("Tasks, \(ticket.view?.doneCount ?? 0) of \(ticket.view?.totalCount ?? 0), \(TopicStatus(ticket).label)")
            .accessibilityIdentifier("tasks-toggle")
    }
    private var tasksSheet: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("Tasks").themeFont(18, .semibold)
                    Spacer()
                    Button { tasksShown = false } label: { Image(systemName: "xmark").frame(width: 44, height: 44).background(Theme.surface3, in: Circle()) }
                        .accessibilityLabel("Close tasks").accessibilityIdentifier("tasks-close")
                }
                Text("\(title) · \(ticket.map { TopicStatus($0).label } ?? "")").themeFont(13).foregroundStyle(Theme.muted)
                if let view = ticket?.view {
                    ProgressBar(done: view.doneCount, total: view.totalCount)
                    ForEach(Array(view.checklist.enumerated()), id: \.offset) { _, task in
                        HStack(spacing: 16) {
                            Image(systemName: task.done ? "checkmark" : "circle").foregroundStyle(Theme.brand).accessibilityHidden(true)
                            Text(task.text).themeFont(15).fixedSize(horizontal: false, vertical: true)
                        }.frame(minHeight: 38).accessibilityElement(children: .combine).accessibilityValue(task.done ? "Done" : "Not done")
                        Divider().overlay(Theme.border)
                    }
                }
            }.padding(16)
        }.foregroundStyle(Theme.text).presentationBackground(Theme.surface)
            .presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
    }
    private var messages: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 8) {
                    if items.isEmpty { emptyState }
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                        if index == 0 || dayKey(item.at) != dayKey(items[index - 1].at) { DayDivider(dayLabel(item.at)) }
                        row(item, index: index).id(item.id)
                    }
                    Color.clear.frame(height: 1).id("conversation-bottom")
                }.padding(.horizontal, 16).padding(.vertical, 10)
            }.defaultScrollAnchor(.bottom).scrollDismissesKeyboard(.interactively)
                .accessibilityIdentifier("message-list")
                .onScrollGeometryChange(for: Bool.self) { geometry in
                    geometry.contentOffset.y + geometry.containerSize.height >= geometry.contentSize.height + geometry.contentInsets.bottom - 45
                } action: { _, bottom in
                    atBottom = bottom
                    if bottom { rememberRead() }
                }
                .overlay(alignment: .bottomTrailing) {
                    if !atBottom {
                        Button { scroll(proxy, to: "conversation-bottom", anchor: .bottom) } label: { JumpToLatestButton(count: unread) }
                            .buttonStyle(PressStyle()).accessibilityIdentifier("jump-latest").padding(12)
                    }
                }
                .onChange(of: items.last?.id) { _, _ in
                    if atBottom || items.last?.side == .me { scroll(proxy, to: "conversation-bottom", anchor: .bottom) }
                }
                .onChange(of: model.focusedQuestion) { _, focus in focusQuestion(focus, proxy: proxy) }
                .task(id: items.count) {
                    if !loaded || atBottom { rememberRead() }
                    loaded = true
                    if scrolledQuestion != model.focusedQuestion { focusQuestion(model.focusedQuestion, proxy: proxy) }
                }
        }
    }
    @ViewBuilder private func row(_ item: ConvItem, index: Int) -> some View {
        let language = LanguageLabel.conversationLanguage(items)
        let retry: () -> Void = { Task { await model.retrySend(item.clientId ?? "") } }
        let discard: () -> Void = { model.discardSend(item.clientId ?? "") }
        if item.kind == .question {
            let stale = item.answer == nil && items.dropFirst(index + 1).contains { $0.side == .them && $0.kind == .message && $0.label != nil }
            QuestionCard(item: item, conversationId: resolved, onReply: { question in
                reply = ReplyPreview(messageId: question.id, title: "Answering \(workspaceName)", quote: question.message.body.text)
            }, onOpenArtifact: hooks.openArtifact, isStale: stale)
        } else if item.side == .me && item.voice != nil {
            OwnVoiceBubble(item: item, conversationLanguage: language, onRetry: retry, onDiscard: discard)
        } else if item.side == .them && item.canPlay && item.speak != nil {
            AgentMemoBubble(item: item, conversationId: resolved, workspaceName: workspaceName)
        } else {
            MessageBubble(item: item, conversationId: resolved, conversationLanguage: language, workspaceName: workspaceName,
                          quotedText: item.replyTo.flatMap { key in items.first { $0.id == key }?.preview },
                          onRetry: retry, onDiscard: discard, onOpenArtifact: hooks.openArtifact)
        }
    }
    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "bubble.left.and.bubble.right").themeFont(32).foregroundStyle(Theme.brand)
            if case .general = resolved {
                Text("Say hello to \(workspaceName)").themeFont(20, .semibold)
                Text("Anything you write here goes to General.").themeFont(15).foregroundStyle(Theme.muted)
            } else { Text("Nothing here yet").themeFont(17).foregroundStyle(Theme.muted) }
        }.multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.vertical, 48)
    }
    private func rememberRead() { seenIncoming = Set(items.filter(\.incoming).map(\.id)); model.markRead(resolved) }
    private func focusQuestion(_ focus: String?, proxy: ScrollViewProxy) {
        guard let focus, items.contains(where: { $0.id == focus }) else { return }
        scrolledQuestion = focus
        scroll(proxy, to: focus, anchor: .center)
    }
    private func scroll(_ proxy: ScrollViewProxy, to id: String, anchor: UnitPoint) {
        if reduceMotion { proxy.scrollTo(id, anchor: anchor) }
        else { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(id, anchor: anchor) } }
    }
    private func date(_ iso: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: iso) { return date }
        formatter.formatOptions.insert(.withFractionalSeconds)
        return formatter.date(from: iso)
    }
    private func dayKey(_ iso: String) -> String { date(iso).map { String(Calendar.current.startOfDay(for: $0).timeIntervalSince1970) } ?? String(iso.prefix(10)) }
    private func dayLabel(_ iso: String) -> String {
        guard let date = date(iso) else { return String(iso.prefix(10)) }
        if Calendar.current.isDateInToday(date) { return "Today" }
        if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
        let formatter = DateFormatter(); formatter.dateFormat = "EEE d MMM"
        return formatter.string(from: date)
    }
}
