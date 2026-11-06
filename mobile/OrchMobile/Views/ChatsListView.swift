import SwiftUI

/// The Chats tab: workspaces as chatrooms with their ticket chats nested below.
struct ChatsListView: View {
    @Environment(AppModel.self) private var model
    @State private var query = ""
    @State private var filter: ChatFilter = .all

    var body: some View {
        @Bindable var model = model
        NavigationStack(path: $model.path) {
            ZStack(alignment: .bottomTrailing) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ModelMessage().padding(.bottom, 8)
                        searchField
                        chips
                        content
                    }.padding(.horizontal, 16).padding(.bottom, 90)
                }.refreshable { await model.refresh() }
                if !model.workspaces.isEmpty {
                    NavigationLink(value: ChatRoute.newChat) {
                        Label("New chat", systemImage: "square.and.pencil").themeFont(15, .semibold).foregroundStyle(Theme.onBrand)
                            .padding(.horizontal, 18).frame(minHeight: 50).background(Theme.brand, in: Capsule())
                    }.padding(16).accessibilityIdentifier("new-chat")
                }
            }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Chats")
            .toolbarColorScheme(.dark, for: .navigationBar)
            .navigationDestination(for: ChatRoute.self) { route in
                switch route {
                case .workspace(let id): ChatRoomView(workspaceId: id)
                case .ticket(let ws, let t): TicketChatView(workspaceId: ws, ticketId: t)
                case .newChat: NewChatView()
                case .newTopic(let ws): NewTopicView(workspaceId: ws)
                case .info(let ws, let t): ChatInfoView(workspaceId: ws, ticketId: t)
                }
            }
        }
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(Theme.muted).accessibilityHidden(true)
            TextField("Search chats and messages", text: $query).themeFont(15).textInputAutocapitalization(.never).autocorrectionDisabled()
                .accessibilityIdentifier("chat-search")
            if !query.isEmpty { Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.muted).frame(width: 44, height: 44) }.accessibilityLabel("Clear search") }
        }.padding(.leading, 14).frame(minHeight: 46).background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.border)).padding(.vertical, 8)
    }

    private var chips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(ChatFilter.allCases) { f in
                    Button { filter = f } label: {
                        Text(f.rawValue).themeFont(13).padding(.horizontal, 12).frame(minHeight: 36)
                            .foregroundStyle(filter == f ? Theme.brand : Theme.muted)
                            .background(filter == f ? Theme.brand.opacity(0.1) : Color.clear, in: Capsule())
                            .overlay(Capsule().stroke(filter == f ? Theme.brand : Theme.borderStrong))
                    }.buttonStyle(PressStyle()).accessibilityAddTraits(filter == f ? .isSelected : []).accessibilityIdentifier("filter-\(f.rawValue)")
                }
            }
        }.padding(.bottom, 8)
    }

    @ViewBuilder private var content: some View {
        let rooms = model.chatRooms
        if !query.trimmingCharacters(in: .whitespaces).isEmpty {
            searchResults(ChatBuilder.search(query, model.chatData, rows: rooms))
        } else if !model.hasLoaded && model.message == nil {
            ForEach(0..<3, id: \.self) { _ in roomRowView(placeholderRow) }.skeleton(true).accessibilityHidden(true)
        } else if model.workspaces.isEmpty {
            VStack(spacing: 12) {
                Image(systemName: "bubble.left.and.bubble.right").font(.system(size: 34)).foregroundStyle(Theme.brand)
                Text("No chats yet").themeFont(18, .semibold)
                Text("Pair a workspace to bring your work here.").themeFont(14).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
                Button("Pair a workspace") { model.tab = .settings }.buttonStyle(SecondaryButtonStyle()).frame(maxWidth: 220)
            }.frame(maxWidth: .infinity).padding(.top, 70).accessibilityIdentifier("chats-empty")
        } else {
            let shown = ChatBuilder.filtered(rooms, filter)
            if shown.isEmpty {
                Text(filter == .needsYou ? "Nothing needs you right now." : "Nothing here yet.").themeFont(14).foregroundStyle(Theme.muted).padding(.top, 24)
            }
            if filter == .needsYou, !shown.isEmpty {
                let n = shown.reduce(0) { $0 + $1.openQuestions }
                Text("\(n) question\(n == 1 ? "" : "s") waiting").themeFont(13).foregroundStyle(Theme.muted).padding(.bottom, 6)
            }
            if filter == .tickets {
                ForEach(shown.flatMap(\.tickets)) { ticketRowView($0, showWorkspace: true) }
            } else {
                ForEach(shown) { r in
                    roomRowView(r)
                    if filter != .workspaces { ForEach(r.tickets) { ticketRowView($0, showWorkspace: false) } }
                }
            }
        }
    }

    private var placeholderRow: RoomRow {
        RoomRow(workspace: Workspace(id: "x", name: "Workspace name", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0),
                lastLine: "Latest message in this workspace", lastAt: nil, unread: 0, openQuestions: 0, tickets: [])
    }

    private func roomRowView(_ r: RoomRow) -> some View {
        NavigationLink(value: ChatRoute.workspace(r.workspace.id)) {
            HStack(spacing: 12) {
                Avatar(name: r.workspace.displayName, size: 46)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(r.workspace.displayName).themeFont(16, .semibold).lineLimit(1)
                        if r.openQuestions > 0 { Circle().fill(Theme.warn).frame(width: 8, height: 8).accessibilityHidden(true) }
                        Spacer()
                        Text(r.lastAt.map { ChatBuilder.timeText($0) } ?? "").themeFont(12).foregroundStyle(r.unread > 0 ? Theme.brand : Theme.muted)
                    }
                    HStack {
                        Text(r.lastLine).themeFont(14).foregroundStyle(Theme.muted).lineLimit(1)
                        Spacer(minLength: 4)
                        UnreadBadge(count: r.unread)
                    }
                }
            }.padding(.vertical, 10).frame(minHeight: 64).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityIdentifier("room-\(r.workspace.id)")
    }

    private func ticketRowView(_ row: TicketRow, showWorkspace: Bool) -> some View {
        let t = row.ticket
        return NavigationLink(value: ChatRoute.ticket(workspace: t.workspace, ticket: t.ticket ?? "")) {
            HStack(alignment: .top, spacing: 10) {
                Circle().fill(dot(t.status)).frame(width: 8, height: 8).padding(.top, 6).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        KeyTag(key: t.key)
                        Text(t.displayTitle).themeFont(15).lineLimit(1)
                        Spacer(minLength: 4)
                        UnreadBadge(count: row.unread)
                    }
                    Text((showWorkspace ? t.workspaceName + " · " : "") + t.stateLine).themeFont(12).foregroundStyle(Theme.muted).lineLimit(1)
                }
            }.padding(.leading, 58).padding(.vertical, 8).frame(minHeight: 48).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityIdentifier("ticket-\(t.id)")
    }

    private func dot(_ s: Ticket.Status) -> Color { switch s { case .needsYou: Theme.warn; case .working: Theme.brand; case .done: Theme.muted } }

    @ViewBuilder private func searchResults(_ r: ChatSearchResult) -> some View {
        if r.isEmpty { Text("No match on this phone.").themeFont(14).foregroundStyle(Theme.muted).padding(.top, 20) }
        if !r.rooms.isEmpty { Eyebrow(text: "WORKSPACES · \(r.rooms.count)").padding(.vertical, 8); ForEach(r.rooms) { roomRowView($0) } }
        if !r.chats.isEmpty { Eyebrow(text: "CHATS · \(r.chats.count)").padding(.vertical, 8); ForEach(r.chats) { ticketRowView($0, showWorkspace: true) } }
        if !r.messages.isEmpty {
            Eyebrow(text: "MESSAGES · \(r.messages.count)").padding(.vertical, 8)
            ForEach(r.messages) { h in
                NavigationLink(value: h.route) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(h.who).themeFont(12, .semibold).foregroundStyle(Theme.brand)
                        Text(h.text).themeFont(14).lineLimit(2).multilineTextAlignment(.leading)
                    }.orchCard(padding: 12)
                }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).padding(.bottom, 8)
            }
        }
    }
}
