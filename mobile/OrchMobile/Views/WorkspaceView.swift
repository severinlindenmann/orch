import SwiftUI

struct WorkspaceView: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    let workspaceId: String
    @Environment(AppModel.self) private var model
    @State private var showDone = false
    @State private var newTopic = false
    @State private var deleting: ConversationID?
    @State private var toast: ArchiveToast?
    private var summary: WorkspaceSummary? { model.workspaceSummaries.first { $0.id == workspaceId } }
    private var name: String { summary.map { WorkspaceAlias.name(for: $0.workspace) } ?? "Workspace" }
    private var topics: [TopicSummary] {
        summary.map { model.split($0).topics } ?? []
    }

    static let activeOrder: [TopicStatus] = [.waitingOnYou, .review, .working, .paused, .backlog]

    static func helperStatus(name: String, anyWorking: Bool, hasMessages: Bool) -> String? {
        if anyWorking { return "\(name) is working" }
        return hasMessages ? "\(name) is ready" : nil
    }

    private var runningCount: Int {
        summary?.topics.filter { $0.status == .working && !$0.isStarting }.count ?? 0
    }

    private func activeGroups(_ topics: [TopicSummary]) -> [(status: TopicStatus, topics: [TopicSummary])] {
        Self.activeOrder.compactMap { status in
            let group = topics.filter { $0.isStarting ? status == .working : $0.status == status }
            return group.isEmpty ? nil : (status, group)
        }
    }

    /// Finished topics by outcome, built once per render (empty groups left out).
    private func doneGroups(_ topics: [TopicSummary]) -> [(status: TopicStatus, topics: [TopicSummary])] {
        [TopicStatus.done, .dropped, .stopped, .didntWork].compactMap { status in
            let group = topics.filter { !$0.isStarting && $0.status == status }
            return group.isEmpty ? nil : (status, group)
        }
    }

    var body: some View {
        let _ = aliasRevision
        let parts = summary.map { model.split($0) }
        let finished = doneGroups(topics)
        List {
            Group {
                ModelMessage()
                MobileModeBanner(workspaceId: workspaceId)
                if parts?.general ?? true { generalCard }
                NowLine(running: runningCount, newCount: summary?.topics.reduce(0) { $0 + $1.unread } ?? 0, scoped: true)
            }.listRowBackground(Color.clear).listRowSeparator(.hidden).listRowInsets(EdgeInsets(top: 9, leading: 16, bottom: 9, trailing: 16))
            if topics.isEmpty { emptyState.listRowBackground(Color.clear).listRowSeparator(.hidden) }
            ForEach(activeGroups(topics), id: \.status) { group in
                Section {
                    ForEach(group.topics) { topic in topicRow(topic) }
                } header: {
                    Label("\(group.status.label) · \(group.topics.count)", systemImage: symbol(group.status))
                        .themeFont(13, .semibold)
                        .foregroundStyle(group.status == .waitingOnYou ? Theme.warn : Theme.muted)
                        .textCase(nil)
                }
            }
            if !finished.isEmpty {
                Section {
                    Button { showDone.toggle() } label: {
                        HStack {
                            Text("Done (\(finished.reduce(0) { $0 + $1.topics.count }))").themeFont(17, .semibold)
                            Spacer()
                            Image(systemName: showDone ? "chevron.down" : "chevron.right").accessibilityHidden(true)
                        }.frame(minHeight: 44)
                    }
                    .foregroundStyle(Theme.muted).listRowBackground(Theme.surface)
                    .accessibilityIdentifier("done-toggle")
                    .accessibilityValue(showDone ? "Expanded" : "Collapsed")
                    // The finished chats sit directly under the toggle, no second "Done" header (owner 2A).
                    if showDone {
                        ForEach(finished.flatMap(\.topics)) { topic in topicRow(topic) }
                    }
                }
            }
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
                        }.frame(minHeight: 44)
                    }.foregroundStyle(Theme.text).accessibilityIdentifier("archived-row")
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
                        Text(name).themeFont(17, .semibold).lineLimit(1)
                        PresenceLine(lastSeen: summary?.workspace.lastSeen)
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
            NewTopicScreen(workspaceId: workspaceId, asSheet: true).presentationDetents([.medium, .large])
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
                        Text("Chat").themeFont(17, .semibold)
                        Image(systemName: "bubble.right").themeFont(12).foregroundStyle(Theme.muted).accessibilityHidden(true)
                    }
                    let preview = summary?.general.lastLine ?? ""
                    Text(preview.isEmpty ? "Talk to \(name)" : preview)
                        .themeFont(15).foregroundStyle(Theme.muted).lineLimit(1)
                    if let status = Self.helperStatus(name: name, anyWorking: runningCount > 0, hasMessages: summary?.general.lastAt != nil) {
                        Text(status).themeFont(13).foregroundStyle(Theme.brand)
                    }
                }
                Spacer(minLength: 4)
                ShellBadge(count: summary?.general.unread ?? 0)
                ShellChevron()
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("general-\(workspaceId)").navigationLinkIndicatorVisibility(.hidden)
            .swipeActions(edge: .trailing, allowsFullSwipe: true) { chatMenu(.general(workspace: workspaceId), status: nil) }
            .contextMenu { chatMenu(.general(workspace: workspaceId), status: nil) }
    }

    @ViewBuilder private func topicRow(_ topic: TopicSummary) -> some View {
        if !topic.isStarting, let ticket = topic.id.ticket {
            NavigationLink(value: ChatRoute.ticket(workspace: workspaceId, ticket: ticket)) { topicLabel(topic) }
                .foregroundStyle(Theme.text).accessibilityIdentifier("ticket-\(workspaceId)|\(ticket)").navigationLinkIndicatorVisibility(.hidden)
                .listRowBackground(Theme.surface).listRowInsets(EdgeInsets()).listRowSeparatorTint(Theme.border)
                .swipeActions(edge: .trailing, allowsFullSwipe: true) { chatMenu(topic.id, status: topic.status) }
                .contextMenu { chatMenu(topic.id, status: topic.status) }
        } else { topicLabel(topic).listRowBackground(Theme.surface).listRowInsets(EdgeInsets()) }
    }

    private func topicLabel(_ topic: TopicSummary) -> some View {
        HStack(spacing: 18) {
            Image(systemName: topic.isStarting ? "clock" : symbol(topic.status))
                .themeFont(20).foregroundStyle(color(topic.status)).frame(width: 24).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text([topic.key, topic.title].compactMap { $0 }.joined(separator: " · "))
                    .themeFont(17, .semibold).lineLimit(3).multilineTextAlignment(.leading)
                Text(subtitle(topic)).themeFont(13).foregroundStyle(Theme.muted)
            }.frame(maxWidth: .infinity, alignment: .leading)
            ShellBadge(count: topic.unread)
            if !topic.isStarting { ShellChevron() }
        }.padding(.horizontal, 16).padding(.vertical, 18).frame(minHeight: 72).contentShape(Rectangle())
    }
    private func subtitle(_ topic: TopicSummary) -> String {
        if topic.isStarting { return "Getting started…" }
        let day = ShellTime.day(topic.lastAt)
        let finished = [TopicStatus.done, .dropped, .stopped, .didntWork].contains(topic.status)
        return topic.status.chip + (finished && !day.isEmpty ? " · " + day : "")
    }
    private func symbol(_ status: TopicStatus) -> String {
        switch status { case .waitingOnYou: "bubble.left"; case .working: "clock"; case .review: "eye"; case .paused: "pause.circle"; case .backlog: "circle"; case .done: "checkmark"; case .dropped: "xmark"; case .stopped: "stop.fill"; case .didntWork: "exclamationmark.triangle" }
    }
    private func color(_ status: TopicStatus) -> Color {
        switch status { case .waitingOnYou: Theme.warn; case .paused, .dropped, .stopped: Theme.muted; case .didntWork: Theme.danger; default: Theme.brand }
    }
    private var emptyState: some View {
        VStack(spacing: 14) {
            OrbitMark().frame(width: 46, height: 46)
            Text("Nothing here yet.").themeFont(20, .semibold)
            Text("Start a topic when you have something to work on.").themeFont(15).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(.vertical, 54)
    }
}
