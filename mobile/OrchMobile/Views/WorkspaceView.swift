import SwiftUI

struct WorkspaceView: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    let workspaceId: String
    @Environment(AppModel.self) private var model
    @State private var newTopic = false
    @State private var deleting: ConversationID?
    @State private var toast: ArchiveToast?
    @Environment(\.dynamicTypeSize) private var typeSize
    private var summary: WorkspaceSummary? { model.workspaceSummaries.first { $0.id == workspaceId } }
    private var name: String { summary.map { WorkspaceAlias.name(for: $0.workspace) } ?? "Workspace" }

    static let activeOrder: [TopicStatus] = [.waitingOnYou, .review, .working, .paused, .backlog]

    /// The Chat card's one status line: an unread helper reply wins, then working, then the last message; nothing yet invites a first message.
    static func helperLine(name: String, anyWorking: Bool, lastLine: String, unread: Int = 0) -> String {
        if anyWorking && unread == 0 { return "\(name) is working…" }
        let line = lastLine.trimmingCharacters(in: .whitespacesAndNewlines)
        return line.isEmpty ? "Talk to \(name)" : line
    }

    private var runningCount: Int {
        summary?.topics.filter { $0.status == .working && !$0.isStarting }.count ?? 0
    }

    var body: some View {
        let _ = aliasRevision
        let parts = summary.map { model.split($0) }
        List {
            Group {
                ModelMessage()
                AcceptWorkspaceCard(workspaceId: workspaceId)
                MobileModeBanner(workspaceId: workspaceId)
                ToolAlertBanner(workspaceId: workspaceId)
            }.listRowBackground(Color.clear).listRowSeparator(.hidden).listRowInsets(EdgeInsets(top: 9, leading: 16, bottom: 9, trailing: 16))
            // Same card margins as the Archived section below (P14).
            if parts?.general ?? true {
                Section { generalCard.listRowBackground(Theme.surface).listRowInsets(EdgeInsets()) }
            }
            // Topics are not listed here (owner 21 Nov, ORCH-1169): every ticket's chat is under Ticket chats on Chats.
            if let count = parts?.archived.count, count > 0 {
                Section {
                    NavigationLink { ArchivedView(workspaceId: workspaceId) } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "archivebox").themeFont(20).foregroundStyle(Theme.muted)
                                .frame(width: 24).accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Archived").themeFont(17, .semibold)
                                Text("\(count) chat\(count == 1 ? "" : "s")").themeFont(13).foregroundStyle(Theme.muted)
                            }
                            Spacer()
                            ShellChevron()
                        }.frame(minHeight: 44)
                    }.foregroundStyle(Theme.text).accessibilityIdentifier("archived-row").navigationLinkIndicatorVisibility(.hidden)
                        .accessibilityLabel("Archived").accessibilityValue("\(count) chat\(count == 1 ? "" : "s")")
                        .listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
                        .listRowBackground(Theme.surface).listRowSeparator(.hidden)
                }
            }
        }.listStyle(.insetGrouped).scrollContentBackground(.hidden).listSectionSpacing(14)
        .background(Theme.bg.ignoresSafeArea()).navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: 10) {
                    WorkspaceBadge(name: name, icon: summary?.workspace.icon, color: summary?.workspace.color, size: 32, id: "header-\(workspaceId)")
                    VStack(alignment: .leading, spacing: 3) {
                        Text(name).themeFont(17, .semibold).lineLimit(ChatsRowRules.titleLines(typeSize.isAccessibilitySize))
                        if ChatsRowRules.showsHeaderSubtitle(typeSize.isAccessibilitySize) { PresenceLine(lastSeen: summary?.workspace.lastSeen) }
                    }
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                TimelineView(.everyMinute) { context in
                    ChatMuteButton(name: name, muted: summary?.workspace.isMuted(now: context.date) ?? false) { mute in
                        Task { await model.setMute(workspaceId, mute) }
                    }
                }
            }.chatCircleBackground()
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink(value: ChatRoute.info(workspace: workspaceId, ticket: nil)) {
                    Image(systemName: "info.circle").frame(width: 44, height: 44)
                }.accessibilityLabel("Chat info").accessibilityIdentifier("workspace-info")
            }
        }
        .safeAreaInset(edge: .bottom) {
            Button { newTopic = true } label: { Text("New topic").foregroundStyle(Theme.brand).themeFont(17, .semibold) }
                .buttonStyle(SecondaryButtonStyle()).padding(16).background(Theme.bg)
        }
        .sheet(isPresented: $newTopic) {
            NewTopicScreen(workspaceId: workspaceId, asSheet: true).presentationDetents([.large])
        }
        .refreshable { await model.refresh() }
        .confirmDelete($deleting) { id in model.deleteChat(id) }
        .archiveToast($toast, bottom: 84)
    }

    private func archive(_ id: ConversationID) {
        model.archiveChat(id)
        toast = ArchiveToast(text: "Chat archived") { model.moveBack(id) }
    }
    @ViewBuilder private func chatMenu(_ id: ConversationID, status: TopicStatus?) -> some View {
        // The first trailing action is outermost and handles a full swipe.
        Button { archive(id) } label: { Label("Archive", systemImage: "archivebox") }.tint(Theme.brand)
        if ArchiveStore.canDelete(status) {
            Button(role: .destructive) { deleting = id } label: { Label("Delete", systemImage: "trash") }.tint(Theme.danger)
        }
    }

    private var generalCard: some View {
        NavigationLink { ChatRoomView(workspaceId: workspaceId).toolbar(.visible, for: .navigationBar) } label: {
            HStack(spacing: 12) {
                WorkspaceBadge(name: name, icon: summary?.workspace.icon, color: summary?.workspace.color, size: 50)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 5) {
                        Text("Your helper").themeFont(17, .semibold)
                        Image(systemName: "bubble.right").themeFont(12).foregroundStyle(Theme.muted).accessibilityHidden(true)
                    }
                    Text(Self.helperLine(name: name, anyWorking: runningCount > 0, lastLine: summary?.general.lastLine ?? "", unread: summary?.general.unread ?? 0))
                        .themeFont(15).foregroundStyle(Theme.muted).lineLimit(ChatsRowRules.detailLines(typeSize.isAccessibilitySize))
                }
                Spacer(minLength: 4)
                ShellBadge(count: summary?.general.unread ?? 0)
                ShellChevron()
            }.padding(.horizontal, 16).padding(.vertical, 14).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("general-\(workspaceId)").navigationLinkIndicatorVisibility(.hidden)
            .swipeActions(edge: .trailing, allowsFullSwipe: true) { chatMenu(.general(workspace: workspaceId), status: nil) }
            .contextMenu { chatMenu(.general(workspace: workspaceId), status: nil) }
    }

}
