import SwiftUI

/// A tappable "RIG-4 started ›" line under General: the workspace acked a message with a new ticket.
struct StartedChip: Identifiable, Equatable {
    let id: String          // the ack's message id: one chip per ack
    let at: String
    let workspace: String
    let ticket: String
    let label: String
}

/// Pure rules of the conversation screen (unit-tested).
enum ConversationRules {
    static func showsWriteOwn(_ q: Question) -> Bool {
        !q.isAllow && !q.message.body.options.isEmpty
    }

    /// The General "<ws> is working…" line ends this long after the last ack/working, even with no new message.
    static let generalWorkingTimeout: TimeInterval = 600   // 10 min, the group-chat contract (#294 §1)

    /// General shows "<ws> is working…" while the last item is this phone's text with a Working receipt, for at most `timeout`
    /// after the last ack/working. A later workspace text ends it (it becomes the last item). General carries no result, failure or
    /// stopped update and no ticket_view (contracts/relay-api.md: only ack and working), so no run-end signal can reach it; the
    /// timeout is what ends a run that stopped without answering.
    static func generalWorking(_ items: [ConvItem], now: Date, timeout: TimeInterval = generalWorkingTimeout) -> Bool {
        guard let last = items.last, last.side == .me, last.receipt == .started else { return false }
        guard let since = last.workingSince.flatMap(date) else { return true }
        return now.timeIntervalSince(since) < timeout
    }

    /// General: a "Working" receipt ends (plain ✓✓) once the workspace answered after it, or `timeout` after the last
    /// ack/working — the same rule and constant as `generalWorking`, so the label and the line always agree.
    static func endingGeneralReceipts(_ items: [ConvItem], now: Date, timeout: TimeInterval = generalWorkingTimeout) -> [ConvItem] {
        let lastReply = items.lastIndex { $0.side == .them } ?? -1
        return items.enumerated().map { i, item in
            guard item.side == .me, item.receipt == .started else { return item }
            let timedOut = item.workingSince.flatMap(date).map { now.timeIntervalSince($0) >= timeout } ?? false
            guard i < lastReply || timedOut else { return item }
            var ended = item
            ended.receipt = .delivered
            return ended
        }
    }

    static func date(_ iso: String) -> Date? {
        let s = String(iso.prefix(while: { $0 != "~" }))
        let f = ISO8601DateFormatter()
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: s)
    }

    /// An open question is stale once the workspace has moved on: a later result/failure/stopped line exists.
    static func isStale(index: Int, in items: [ConvItem]) -> Bool {
        let q = items[index]
        guard q.kind == .question, q.answer == nil else { return false }
        return items.dropFirst(index + 1).contains { $0.side == .them && $0.kind == .message && $0.label != nil }
    }

    /// "2 of 5 · Working"; with no checklist only the status ("Working").
    static func summaryText(done: Int, total: Int, status: String, separator: String = " · ") -> String {
        total > 0 ? "\(done) of \(total)\(separator)\(status)" : status
    }

    /// General only: acks (a workspace text with `reply_to`) naming a ticket for a General text of this phone.
    static func startedChips(messages: [PhoneMessage], workspace: String, key: (String) -> String?) -> [StartedChip] {
        let generalAt = Dictionary(messages.filter { $0.fromPhone && $0.workspaceId == workspace && $0.message.body.general == true }.map { ($0.id, $0.message.createdAt) },
                                   uniquingKeysWith: { a, _ in a })
        let general = Set(generalAt.keys)
        var seen = Set<String>(), out: [StartedChip] = []
        for pm in messages.sorted(by: { $0.message.createdAt < $1.message.createdAt }) where !pm.fromPhone && pm.workspaceId == workspace {
            guard pm.message.body.update?.kind == "ack", let t = pm.message.ticket, let r = pm.message.replyTo, general.contains(r),
                  seen.insert(pm.id).inserted else { continue }
            // After the message it answers (clocks of phone and workspace may differ): never above it.
            out.append(StartedChip(id: pm.id, at: max(pm.message.createdAt, generalAt[r] ?? ""), workspace: workspace, ticket: t, label: "\(pm.message.key ?? key(t) ?? "Topic") started"))
        }
        return out
    }
}

private enum ConversationFormat {
    nonisolated(unsafe) static let day: DateFormatter = { let f = DateFormatter(); f.dateFormat = "EEE d MMM"; return f }()
    nonisolated(unsafe) static let iso = ISO8601DateFormatter()
    nonisolated(unsafe) static let isoFraction: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions.insert(.withFractionalSeconds); return f }()
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
    var historyDay: String? = nil
    var goToToday: (() -> Void)? = nil
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    @State private var historyShown = false
    @State private var dayDetails = false
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var viewing: ArtifactItem?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var reply: ReplyPreview?
    @State private var tasksShown = false
    @State private var atBottom = true
    @State private var loaded = false
    @State private var scrolledQuestion: String?
    @State private var seenIncoming: Set<String> = []
    private var resolved: ConversationID { model.resolve(id) }
    /// One clock for the General "Working" receipt and the "is working…" line, so both end together.
    @State private var now = Date()
    private var isGeneral: Bool { if case .general = resolved { true } else { false } }
    private var today: String { ChatDay.key(for: now) }
    private var allItems: [ConvItem] {
        let all = model.conversationItems(resolved)
        if case .general = resolved { return ConversationRules.endingGeneralReceipts(all, now: now) }
        return all
    }
    private var items: [ConvItem] {
        guard isGeneral else { return allItems }
        if let historyDay { return allItems.filter { ChatDay.key(of: $0) == historyDay } }
        return ChatDay.split(allItems, today: today).today
    }
    private var workspaceName: String {
        let _ = aliasRevision
        return model.workspace(resolved.workspace).map { WorkspaceAlias.name(for: $0) } ?? "Workspace"
    }
    private var ticket: Ticket? { model.tickets.first { $0.workspace == resolved.workspace && $0.ticket == resolved.ticket && resolved.ticket != nil } }
    private var topicSummary: String? {
        guard historyDay == nil, case .topic = resolved,
              let summary = ticket?.view?.summary?.trimmingCharacters(in: .whitespacesAndNewlines),
              !summary.isEmpty else { return nil }
        return summary
    }
    private var title: String {
        switch resolved {
        case .general: historyDay.map { ChatDay.label(forDay: $0, today: today) + " · read only" } ?? "Chat"
        case .starting: "New topic"
        case .topic: ticket.map { [$0.key, $0.displayTitle].compactMap { $0 }.joined(separator: " · ") } ?? "Topic"
        }
    }
    private func working(_ items: [ConvItem], now: Date) -> Bool {
        if let ticket { return TopicStatus(ticket) == .working }
        if case .general = resolved { return ConversationRules.generalWorking(items, now: now) }
        return false
    }
    private func unread(_ items: [ConvItem]) -> Int { items.filter { $0.incoming && !seenIncoming.contains($0.id) }.count }

    var body: some View {
        let items = self.items
        VStack(spacing: 0) {
            if model.speech.isActive { MiniPlayer() }
            OfflineBanner()
            if let ticket {
                summary(ticket)
                HStack {
                    Text("Chat").themeFont(17, .semibold)
                    Spacer()
                    if let answered = ConversationRules.answeredText(in: items) {
                        Text(answered).themeFont(13).foregroundStyle(Theme.muted)
                    }
                }.padding(.horizontal, 16).padding(.vertical, 12)
            }
            messages(items)
        }
            // Keep the message area dark without letting it paint the status-bar safe area.
            .background(Theme.bg, ignoresSafeAreaEdges: .bottom)
            .background(Theme.bg.ignoresSafeArea(edges: .top))
            .foregroundStyle(Theme.text).accessibilityElement(children: .contain).accessibilityIdentifier("conversation-view")
            .toolbar {
                ToolbarItem(placement: .principal) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(title).themeFont(16, .semibold).lineLimit(1).accessibilityIdentifier("chat-title")
                        presence
                    }
                    .padding(.vertical, 8)
                }
                if isGeneral && historyDay == nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { historyShown = true } label: {
                            VStack(spacing: 2) { Image(systemName: "clock"); Text("History").themeFont(11) }
                                .frame(minWidth: 44, minHeight: 44)
                        }.accessibilityIdentifier("chat-history")
                    }
                }
                if historyDay == nil {
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink(value: ChatRoute.info(workspace: resolved.workspace, ticket: resolved.ticket)) {
                        Image(systemName: "info.circle").themeFont(18).frame(minWidth: 44, minHeight: 44)
                    }.accessibilityLabel("Chat info").accessibilityIdentifier("chat-info")
                }
                }
            }
            .navigationBarTitleDisplayMode(.inline).toolbarColorScheme(.dark, for: .navigationBar)
            .toolbarBackground(Theme.bg, for: .navigationBar).toolbarBackground(.visible, for: .navigationBar)
            .tint(Theme.brand)
            .safeAreaInset(edge: .bottom, spacing: 0) {
                VStack(spacing: 0) {
                    if historyDay != nil {
                        Button("Go to Today") { goToToday?() }.buttonStyle(WideButtonStyle(color: Theme.brand))
                    } else {
                    if working(items, now: now) { StatusLine(isGeneral ? "\(workspaceName) helper is thinking…" : "\(workspaceName) is working…") }
                    if let ticketId = resolved.ticket, let q = ReviewRules.reviewQuestion(ticket: ticket, workspaceId: resolved.workspace, ticketId: ticketId, questions: model.questions, answers: model.answers) {
                        ReviewBar(question: q) { reply = ReplyPreview(messageId: q.id, title: "Changes:", quote: "", answering: q) }
                    }
                    Composer(target: resolved.target, note: resolved.ticket == nil ? nil : ChatBuilder.composerNote(running: ticket?.view?.running, finished: ticket.map { [.done, .dropped, .stopped, .didntWork].contains(TopicStatus($0)) } ?? false), reply: $reply)
                    }
                }
            }
            .sheet(isPresented: $historyShown) { ChatHistoryView(workspaceId: resolved.workspace) }
            .sheet(isPresented: $dayDetails) {
                Text("The helper starts each day fresh at 04:00. Yesterday's chat stays in History. Nothing is deleted.")
                    .themeFont(17).foregroundStyle(Theme.text).padding(24)
                    .presentationDetents([.medium]).presentationBackground(Theme.surface).presentationDragIndicator(.visible)
            }
            .sheet(isPresented: $tasksShown) { tasksSheet }
            .fullScreenCover(item: $viewing) { ArtifactViewer(item: $0) }
            // the clock: the General receipt and line also end by the timeout without a new message
            .task {
                while !Task.isCancelled {
                    now = Date()
                    try? await Task.sleep(for: .seconds(15))
                }
            }
    }
    @ViewBuilder private var presence: some View {
        if case .starting = resolved { Text("Getting started…").themeFont(13).foregroundStyle(Theme.muted) }
        else {
            HStack(spacing: 4) {
                if isGeneral { Text("\(workspaceName) helper ·") }
                else if resolved.ticket != nil { Text("\(workspaceName) ·") }
                TimelineView(.everyMinute) { context in
                    let presence = model.presence(of: resolved.workspace, now: context.date)
                    HStack(spacing: 4) {
                        if presence.isOnline { PresenceDot() }
                        Text(presence.line(now: context.date))
                    }
                }
            }.themeFont(13).foregroundStyle(Theme.muted)
        }
    }
    private func summary(_ ticket: Ticket) -> some View {
        Button { tasksShown = true } label: {
            HStack {
                if [.waitingOnYou, .review].contains(TopicStatus(ticket)) {
                    TicketStatusChip(status: TopicStatus(ticket))
                }
                if !([.waitingOnYou, .review].contains(TopicStatus(ticket)) && (ticket.view?.totalCount ?? 0) == 0) {
                    Text(ConversationRules.summaryText(done: ticket.view?.doneCount ?? 0, total: ticket.view?.totalCount ?? 0, status: TopicStatus(ticket).label))
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.down")
            }.themeFont(13).foregroundStyle(Theme.muted).padding(.horizontal, 18).frame(minHeight: 44)
                .padding(.vertical, 4)
                .background(Theme.bg, ignoresSafeAreaEdges: .top)
                .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
        }.buttonStyle(PressStyle()).accessibilityLabel("Tasks, " + ConversationRules.summaryText(done: ticket.view?.doneCount ?? 0, total: ticket.view?.totalCount ?? 0, status: TopicStatus(ticket).label, separator: ", "))
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
                    if view.totalCount > 0 { ProgressBar(done: view.doneCount, total: view.totalCount) }
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
    private enum Row: Identifiable {
        case item(ConvItem, index: Int)
        case chip(StartedChip)
        var id: String { switch self { case .item(let i, _): i.id; case .chip(let c): "chip-" + c.id } }
        var at: String { switch self { case .item(let i, _): i.at; case .chip(let c): c.at } }
        var isChip: Bool { if case .chip = self { true } else { false } }
    }
    private func rows(_ items: [ConvItem]) -> [Row] {
        var all = items.enumerated().map { Row.item($0.element, index: $0.offset) }
        if case .general(let ws) = resolved {
            all += ConversationRules.startedChips(messages: model.messages, workspace: ws, key: { model.ticket(ws, $0)?.key }).filter { chip in
                let key = ChatDay.key(of: ConvItem(id: chip.id, at: chip.at, side: .them))
                return key == (historyDay ?? today)
            }.map(Row.chip)
            // By time; at the same time a chip comes after the message it belongs to.
            all.sort { ($0.at, $0.isChip ? 1 : 0, $0.id) < ($1.at, $1.isChip ? 1 : 0, $1.id) }
        }
        return all
    }
    private func messages(_ items: [ConvItem]) -> some View {
        let language = LanguageLabel.conversationLanguage(items)
        let rows = rows(items)
        let waiting = Dictionary(model.outbox.items.compactMap { o in QueuedNote.text(for: o).map { (o.clientId, $0) } }, uniquingKeysWith: { a, _ in a })
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 8) {
                    if let topicSummary {
                        NavigationLink(value: ChatRoute.info(workspace: resolved.workspace, ticket: resolved.ticket)) {
                            Text(topicSummary).themeFont(15).foregroundStyle(Theme.muted).lineLimit(3)
                                .multilineTextAlignment(.leading).frame(maxWidth: .infinity, alignment: .leading)
                                .padding(14).background(Theme.surface2, in: RoundedRectangle(cornerRadius: 12))
                        }.buttonStyle(PressStyle()).accessibilityIdentifier("topic-summary")
                    }
                    if isGeneral && historyDay == nil && !items.isEmpty && !ChatDay.split(allItems, today: today).past.isEmpty {
                        VStack(spacing: 6) {
                            Text("New day").themeFont(13, .medium)
                            Button("Context cleared at 04:00 · Details") { dayDetails = true }.themeFont(13)
                        }.foregroundStyle(Theme.muted).frame(maxWidth: .infinity).padding(.vertical, 16)
                            .accessibilityIdentifier("chat-newday")
                    }
                    if items.isEmpty { emptyState }
                    ForEach(Array(rows.enumerated()), id: \.element.id) { n, row in
                        if n == 0 || rowDay(row) != rowDay(rows[n - 1]) {
                            DayDivider(isGeneral ? ChatDay.label(forDay: rowDay(row), today: today) : dayLabel(row.at))
                        }
                        Group {
                            switch row {
                            case .item(let item, let index): self.row(item, index: index, items: items, language: language, waiting: waiting)
                            case .chip(let chip): chipView(chip)
                            }
                        }.id(row.id)
                    }
                    // At the bottom exactly while this end marker is on screen (the jump row's own inset cannot confuse it).
                    Color.clear.frame(height: 1).id("conversation-bottom")
                        .onAppear { atBottom = true; rememberRead() }
                        .onDisappear { atBottom = false }
                }.padding(.horizontal, 16).padding(.vertical, 10)
            }.defaultScrollAnchor(.bottom).scrollDismissesKeyboard(.interactively)
                .accessibilityIdentifier("message-list")
                // Not an overlay: the button takes its own row above the composer, so it never covers a bubble.
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    if !atBottom {
                        Button { scroll(proxy, to: "conversation-bottom", anchor: .bottom) } label: { JumpToLatestButton(count: unread(items)) }
                            .buttonStyle(PressStyle()).accessibilityIdentifier("jump-latest")
                            .frame(maxWidth: .infinity, alignment: .trailing).padding(.horizontal, 12).padding(.bottom, 12)
                    }
                }
                .onChange(of: items.last?.id) { _, _ in
                    if atBottom || items.last?.side == .me { scroll(proxy, to: "conversation-bottom", anchor: .bottom) }
                    rememberRead(bottomSeen: atBottom)   // the open conversation is read, also while scrolled up
                }
                .onChange(of: model.focusedQuestion) { _, focus in focusQuestion(focus, proxy: proxy) }
                .task(id: items.count) {
                    rememberRead(bottomSeen: !loaded || atBottom)
                    loaded = true
                    if scrolledQuestion != model.focusedQuestion { focusQuestion(model.focusedQuestion, proxy: proxy) }
                }
        }
    }
    /// A tap on a picture, file or preview in the conversation: `id` is a blob id, or the id of a topic attachment / question preview.
    private func openArtifact(_ id: String) {
        let found = model.conversationItems(resolved).lazy.flatMap(\.attachments).first { $0.blobId == id }.map { ArtifactItem($0, in: resolved) }
            ?? ticket?.view?.attachments.first { $0.id == id || $0.blobId == id || $0.artifactId == id }.map { ArtifactItem($0, in: resolved) }
            ?? model.tickets.lazy.compactMap { $0.view?.attachments.first { $0.id == id } }.first.map { ArtifactItem($0, in: resolved) }
        guard let item = found else { return }
        if item.kind == .link { if let url = item.safeLinkURL { openURL(url) } } else { viewing = item }
    }
    private func chipView(_ chip: StartedChip) -> some View {
        Button {
            if historyDay != nil { goToToday?() }
            model.path.append(.ticket(workspace: chip.workspace, ticket: chip.ticket))
        } label: {
            HStack(spacing: 4) { Text(chip.label); Image(systemName: "chevron.right").themeFont(11, .semibold) }
                .themeFont(13, .semibold).foregroundStyle(Theme.brand).padding(.horizontal, 14).frame(minHeight: 44)
                .background(Theme.surface2, in: Capsule(style: .continuous))
        }.buttonStyle(PressStyle()).frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityLabel("\(chip.label). Open topic").accessibilityIdentifier("started-chip-\(chip.ticket)")
    }
    @ViewBuilder private func row(_ item: ConvItem, index: Int, items: [ConvItem], language: String, waiting: [String: String]) -> some View {
        let retry: () -> Void = { Task { await model.retrySend(item.clientId ?? "") } }
        let discard: () -> Void = { model.discardSend(item.clientId ?? "") }
        let replyHere: () -> Void = { reply = ReplyPreview(messageId: item.id, title: "Answering \(workspaceName)", quote: item.preview) }
        let wait = isGeneral && item.receipt == .queued ? ChatDay.queuedNote : item.clientId.flatMap { waiting[$0] }
        if isGeneral && item.by != nil && item.side == .them &&
            (index == 0 || items[index - 1].by != item.by || items[index - 1].side != .them) {
            ChatHelperLabel(workspace: model.workspace(resolved.workspace))  // never a name from `by`: a workspace speaks only for itself in its Chat
        }
        if item.kind == .question && historyDay == nil {
            let stale = ConversationRules.isStale(index: index, in: items)
            QuestionCard(item: item, conversationId: resolved, onReply: { question in
                reply = ReplyPreview(messageId: question.id, title: "Answering \(workspaceName)", quote: question.message.body.text)
            }, onWriteOwn: { q in
                reply = ReplyPreview(messageId: q.id, title: "Answer:", quote: q.message.body.text, answering: q)
            }, onOpenArtifact: openArtifact, isStale: stale, position: ConversationRules.openPosition(of: item.id, in: items))
        } else if item.side == .me && item.voice != nil {
            OwnVoiceBubble(item: item, conversationLanguage: language, onRetry: historyDay == nil ? retry : {}, onDiscard: historyDay == nil ? discard : {}, onReply: historyDay == nil ? replyHere : nil, waitNote: wait)
        } else if item.side == .them && item.canPlay && item.speak != nil {
            AgentMemoBubble(item: item, conversationId: resolved, workspaceName: workspaceName, onReply: historyDay == nil ? replyHere : nil)
        } else {
            MessageBubble(item: item, conversationId: resolved, conversationLanguage: language, workspaceName: workspaceName,
                          quotedText: item.replyTo.flatMap { key in items.first { $0.id == key }?.preview },
                          onRetry: historyDay == nil ? retry : nil, onDiscard: historyDay == nil ? discard : nil, onOpenArtifact: openArtifact, onReply: historyDay == nil ? replyHere : nil, waitNote: wait)
        }
    }
    @ViewBuilder private var emptyState: some View {
        if topicSummary != nil {
            Text("Updates and results show up in this chat.").themeFont(13).foregroundStyle(Theme.muted)
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 14).padding(.vertical, 8)
        } else {
            VStack(spacing: 12) {
                Image(systemName: "bubble.left.and.bubble.right").themeFont(32).foregroundStyle(Theme.brand)
                if case .general = resolved {
                    Text("Say hello to \(workspaceName) helper").themeFont(20, .semibold)
                    Text("Talk with \(workspaceName) helper here.").themeFont(15).foregroundStyle(Theme.muted)
                } else { Text("Nothing here yet").themeFont(17).foregroundStyle(Theme.muted) }
            }.multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.vertical, 48)
        }
    }
    /// The open conversation is read: new incoming messages are marked read while it is on screen, even when scrolled up
    /// (only the jump button's own count waits until the bottom was seen).
    private func rememberRead(bottomSeen: Bool = true) {
        guard historyDay == nil else { return }
        if bottomSeen { seenIncoming = Set(items.filter(\.incoming).map(\.id)) }
        model.markRead(resolved)
    }
    private func focusQuestion(_ focus: String?, proxy: ScrollViewProxy) {
        guard let focus, items.contains(where: { $0.id == focus }) else { return }
        scrolledQuestion = focus
        scroll(proxy, to: focus, anchor: .center)
    }
    private func scroll(_ proxy: ScrollViewProxy, to id: String, anchor: UnitPoint) {
        if reduceMotion { proxy.scrollTo(id, anchor: anchor) }
        else { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(id, anchor: anchor) } }
    }
    private func rowDay(_ row: Row) -> String {
        guard isGeneral else { return dayKey(row.at) }
        switch row {
        case .item(let item, _): return ChatDay.key(of: item)
        case .chip(let chip): return ChatDay.key(of: ConvItem(id: chip.id, at: chip.at, side: .them))
        }
    }
    private func date(_ iso: String) -> Date? { ConversationFormat.iso.date(from: iso) ?? ConversationFormat.isoFraction.date(from: iso) }
    private func dayKey(_ iso: String) -> String { date(iso).map { String(Calendar.current.startOfDay(for: $0).timeIntervalSince1970) } ?? String(iso.prefix(10)) }
    private func dayLabel(_ iso: String) -> String {
        guard let date = date(iso) else { return String(iso.prefix(10)) }
        if Calendar.current.isDateInToday(date) { return "Today" }
        if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
        return ConversationFormat.day.string(from: date)
    }
}

struct TicketStatusChip: View {
    let status: TopicStatus
    private var color: Color { status == .waitingOnYou ? Theme.warn : status == .review ? Theme.brand : Theme.muted }
    var body: some View {
        Text(status.label).themeFont(13, .medium).foregroundStyle(color)
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(color.opacity(0.16), in: Capsule())
    }
}
