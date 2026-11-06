import SwiftUI

private struct ChatScroll: View {
    @Environment(AppModel.self) private var model
    let chatKey: String
    let items: [ChatItem]
    let workspaceName: String

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    ForEach(items) { item in
                        ChatItemView(item: item, workspaceName: workspaceName).id(item.id)
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }.padding(.horizontal, 14).padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively).defaultScrollAnchor(.bottom)
            .task { await model.watchWhileOpen() }
            .task(id: items.count) {
                model.markRead(chatKey, items: items)
                if let f = model.focusedQuestion, items.contains(where: { $0.id == f }) {
                    try? await Task.sleep(for: .milliseconds(250))
                    withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(f, anchor: .center) }
                }
            }
        }
    }
}

/// Workspace chatroom: my texts, its texts, system lines, ticket cards, questions.
struct ChatRoomView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String

    var body: some View {
        let w = model.workspace(workspaceId)
        let name = w?.displayName ?? "Workspace"
        let items = ChatBuilder.workspaceItems(workspaceId, model.chatData)
        VStack(spacing: 0) {
            OfflineBanner()
            if items.isEmpty && model.hasLoaded {
                emptyState(name).frame(maxHeight: .infinity)
            } else {
                ChatScroll(chatKey: ReadState.workspaceKey(workspaceId), items: items, workspaceName: name)
            }
            Composer(placeholder: "Message \(name)…", note: "A new message starts a new ticket") { text in
                if case .failed = await model.sendChat(to: workspaceId, text: text) { return false }
                return true
            }
        }.background(Theme.bg.ignoresSafeArea()).navigationBarTitleDisplayMode(.inline).toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 8) {
                        Avatar(name: name, size: 30)
                        VStack(alignment: .leading, spacing: 0) {
                            Text(name).themeFont(16, .semibold)
                            Text(w.map { lastSeenText($0.lastSeen, online: $0.online) } ?? "").themeFont(11).foregroundStyle(Theme.muted).lineLimit(1)
                        }
                    }.accessibilityElement(children: .combine).accessibilityIdentifier("chat-title")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink(value: ChatRoute.info(workspace: workspaceId, ticket: nil)) { Image(systemName: "info.circle") }.accessibilityLabel("Chat info")
                }
            }
    }

    private func emptyState(_ name: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "bubble.left").font(.system(size: 32)).foregroundStyle(Theme.brand)
            Text("Say hello to \(name)").themeFont(17, .semibold)
            Text("Your first message starts a ticket.").themeFont(14).foregroundStyle(Theme.muted)
        }.accessibilityIdentifier("room-empty")
    }
}

/// One ticket, one conversation: pinned tasks, history, proof.
struct TicketChatView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String
    let ticketId: String
    @State private var tasksOpen = false

    var body: some View {
        let t = model.ticket(workspaceId, ticketId)
        let name = model.workspace(workspaceId)?.displayName ?? "Workspace"
        let agent = t?.view?.agent ?? "Agent"
        let items = ChatBuilder.ticketItems(workspaceId, ticketId, model.chatData)
        VStack(spacing: 0) {
            OfflineBanner()
            if let v = t?.view, !v.checklist.isEmpty { tasksCard(v).padding(.horizontal, 14).padding(.top, 8) }
            if items.isEmpty && model.hasLoaded {
                VStack(spacing: 8) { Text("Nothing here yet").themeFont(16, .semibold); Text("Updates and results show up in this chat.").themeFont(14).foregroundStyle(Theme.muted) }
                    .frame(maxHeight: .infinity)
            } else {
                ChatScroll(chatKey: ReadState.ticketKey(workspaceId, ticketId), items: items, workspaceName: agent)
            }
            Composer(placeholder: "Message \(agent)…", note: ChatBuilder.composerNote(running: t?.view?.running)) { text in
                if case .failed = await model.sendChat(to: workspaceId, text: text, ticket: ticketId) { return false }
                return true
            }
        }.background(Theme.bg.ignoresSafeArea()).navigationBarTitleDisplayMode(.inline).toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    VStack(spacing: 2) {
                        HStack(spacing: 6) { KeyTag(key: t?.key); Text(t?.displayTitle ?? "Ticket").themeFont(16, .semibold).lineLimit(1) }
                        HStack(spacing: 6) { if let t { StatusPill(status: t.status, kind: t.kind) }; Text(agent).themeFont(11).foregroundStyle(Theme.muted); Text("· \(name)").themeFont(11).foregroundStyle(Theme.muted) }
                    }.accessibilityElement(children: .combine).accessibilityIdentifier("chat-title")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink(value: ChatRoute.info(workspace: workspaceId, ticket: ticketId)) { Image(systemName: "info.circle") }.accessibilityLabel("Chat info")
                }
            }
    }

    private func tasksCard(_ v: TicketSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Button { withAnimation(.easeOut(duration: 0.2)) { tasksOpen.toggle() } } label: {
                HStack {
                    Text("Tasks \(v.doneCount)/\(v.totalCount)").themeFont(14, .semibold)
                    Spacer()
                    Image(systemName: tasksOpen ? "chevron.up" : "chevron.down").foregroundStyle(Theme.muted)
                }.frame(minHeight: 36).contentShape(Rectangle())
            }.buttonStyle(PressStyle()).accessibilityIdentifier("tasks-toggle")
            ProgressBar(done: v.doneCount, total: v.totalCount)
            if tasksOpen {
                ForEach(Array(v.checklist.enumerated()), id: \.offset) { _, task in
                    HStack(spacing: 8) {
                        Image(systemName: task.done ? "checkmark.circle.fill" : "circle").foregroundStyle(task.done ? Theme.brand : Theme.muted)
                        Text(task.text).themeFont(13).foregroundStyle(task.done ? Theme.muted : Theme.text)
                    }.accessibilityElement(children: .combine)
                }
            } else if let next = v.checklist.first(where: { !$0.done }) {
                Text(next.text).themeFont(12).foregroundStyle(Theme.muted)
            }
        }.orchCard(padding: 12).accessibilityIdentifier("tasks-card")
    }
}

/// New chat, step 1: where should it go?
struct NewChatView: View {
    @Environment(AppModel.self) private var model
    @State private var selected: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Eyebrow(text: "NEW CONVERSATION")
            Text("Where should it go?").themeFont(26, .semibold)
            Text("Pick the workspace for this topic.").themeFont(14).foregroundStyle(Theme.muted)
            ScrollView {
                VStack(spacing: 8) {
                    ForEach(model.workspaces) { w in
                        Button { selected = w.id } label: {
                            HStack(spacing: 12) {
                                Avatar(name: w.displayName, size: 38)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(w.displayName).themeFont(16, .semibold)
                                    Text(lastSeenText(w.lastSeen, online: w.online)).themeFont(12).foregroundStyle(Theme.muted)
                                }
                                Spacer()
                                Image(systemName: selected == w.id ? "largecircle.fill.circle" : "circle").foregroundStyle(selected == w.id ? Theme.brand : Theme.muted)
                            }.padding(12).background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
                                .overlay(RoundedRectangle(cornerRadius: 12).stroke(selected == w.id ? Theme.brand : Theme.border))
                                .contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("pick-\(w.id)")
                    }
                }
            }
            Button {
                if let selected { model.path.append(.newTopic(selected)) }
            } label: { Text("Continue") }.buttonStyle(PrimaryButtonStyle(muted: selected == nil)).disabled(selected == nil).accessibilityIdentifier("pick-continue")
        }.padding(16).background(Theme.bg.ignoresSafeArea()).navigationTitle("New chat").navigationBarTitleDisplayMode(.inline)
            .onAppear { if model.workspaces.count == 1 { selected = model.workspaces.first?.id } }
    }
}

/// New chat, step 2: the first message. The workspace answers with a ticket.
struct NewTopicView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String
    @State private var text = ""
    @State private var sending = false
    @State private var voice: VoiceInput?
    @FocusState private var focused: Bool

    var body: some View {
        let name = model.workspace(workspaceId)?.displayName ?? "Workspace"
        let mic = MicInput(voice: voice)
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) { Avatar(name: name, size: 30); Text(name).themeFont(14).foregroundStyle(Theme.muted) }
            TextField(mic.recording ? "Recording your voice…" : mic.transcribing ? "Writing it down…" : "What do you need?", text: $text, axis: .vertical)
                .lineLimit(5...12).focused($focused).themeFont(17).disabled(mic.busy || sending)
                .padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: 14)).overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.borderStrong))
                .accessibilityIdentifier("topic-field")
            HStack(spacing: 10) {
                MicButton(voice: voice, text: $text, disabled: sending)
                Text(voice?.error ?? mic.label).themeFont(12, .medium).foregroundStyle(voice?.error != nil ? Theme.danger : Theme.muted)
                    .accessibilityIdentifier("mic-status")
            }
            Spacer()
            let ok = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !sending && !mic.busy
            Button { sending = true; Task { await model.startTopic(workspaceId: workspaceId, text: text); sending = false } } label: { Text(sending ? "Starting…" : "Start") }
                .buttonStyle(PrimaryButtonStyle(muted: !ok)).disabled(!ok).accessibilityIdentifier("topic-start")
            Text("This starts a new ticket. You get a message when there is a result, a question or a problem.").themeFont(12).foregroundStyle(Theme.muted)
        }.padding(16).background(Theme.bg.ignoresSafeArea()).navigationTitle("New topic in \(name)").navigationBarTitleDisplayMode(.inline)
            .onAppear { if !UserDefaults.standard.bool(forKey: "autoMic") { focused = true } }
            .task {
                if voice == nil { voice = MicInput.make(model) }
                if UserDefaults.standard.bool(forKey: "autoMic") { await voice?.toggle(current: text) }
            }
            .onChange(of: voice?.transcript) { _, t in if let t { text = t } }
            .onDisappear { voice?.stop() }
    }
}

/// Chat info: details and the media, links and files kept with a ticket (or the whole workspace).
struct ChatInfoView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String
    let ticketId: String?
    @State private var tab = 0

    var body: some View {
        let w = model.workspace(workspaceId)
        let t = ticketId.flatMap { model.ticket(workspaceId, $0) }
        let wsTickets = model.tickets.filter { $0.workspace == workspaceId && $0.ticket != nil }
        let atts: [TicketSnapshot.Attachment] = (t.map { [$0] } ?? wsTickets).flatMap { $0.view?.attachments ?? [] }
        let media = atts.filter { $0.kind == "image" }, links = atts.filter { $0.kind == "link" }, files = atts.filter { $0.kind == "file" }
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let t {
                    Text(t.displayTitle).themeFont(24, .semibold)
                    HStack { KeyTag(key: t.key); StatusPill(status: t.status, kind: t.kind) }
                    if let a = t.view?.agent { detail("Agent", a) }
                    detail("Workspace", w?.displayName ?? t.workspaceName)
                    detail("Updated", ChatBuilder.timeText(t.at))
                    if let s = t.view?.summary ?? Optional(t.text), !s.isEmpty {
                        VStack(alignment: .leading, spacing: 4) { Eyebrow(text: "WHERE IT STANDS"); Text(s).themeFont(15) }
                            .padding(.leading, 12).overlay(alignment: .leading) { Rectangle().fill(Theme.brand).frame(width: 3) }
                    }
                } else {
                    Avatar(name: w?.displayName ?? "W", size: 52)
                    Text(w?.displayName ?? "Workspace").themeFont(24, .semibold)
                    Text(w.map { lastSeenText($0.lastSeen, online: $0.online) } ?? "").themeFont(14).foregroundStyle(Theme.muted)
                    if let d = w?.description { Text(d).themeFont(15) }
                    Eyebrow(text: "\(wsTickets.count) TICKETS")
                    ForEach(wsTickets) { x in
                        HStack(spacing: 8) { KeyTag(key: x.key); Text(x.displayTitle).themeFont(14).lineLimit(1); Spacer(); StatusPill(status: x.status, kind: x.kind) }
                    }
                }
                Picker("", selection: $tab) {
                    Text("Media \(media.count)").tag(0); Text("Links \(links.count)").tag(1); Text("Files \(files.count)").tag(2)
                }.pickerStyle(.segmented).accessibilityIdentifier("info-tabs")
                let shown = [media, links, files][tab]
                if shown.isEmpty { Text("Nothing here yet.").themeFont(14).foregroundStyle(Theme.muted) }
                else if tab == 0 {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 8)], spacing: 8) { ForEach(shown) { AttachmentTile(attachment: $0) } }
                } else {
                    ForEach(shown) { AttachmentTile(attachment: $0).padding(.vertical, 4) }
                }
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
        }.background(Theme.bg.ignoresSafeArea()).navigationTitle("Chat info").navigationBarTitleDisplayMode(.inline)
    }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) { Text(label).themeFont(12).foregroundStyle(Theme.muted); Text(value).themeFont(15) }
    }
}
