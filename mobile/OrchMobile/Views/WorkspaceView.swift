import SwiftUI

struct WorkspaceView: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    let workspaceId: String
    @Environment(AppModel.self) private var model
    @State private var done = false
    @State private var newTopic = false
    private var summary: WorkspaceSummary? { model.workspaceSummaries.first { $0.id == workspaceId } }
    private var name: String { summary.map { WorkspaceAlias.name(for: $0.workspace) } ?? "Workspace" }
    private var topics: [TopicSummary] {
        (summary?.topics ?? []).filter { topic in
            let open = topic.isStarting || topic.status == .working || topic.status == .waitingOnYou
            return done ? !open : open
        }
    }

    /// Finished topics by outcome, built once per render (empty groups left out).
    private func doneGroups(_ topics: [TopicSummary]) -> [(status: TopicStatus, topics: [TopicSummary])] {
        [TopicStatus.done, .stopped, .didntWork].compactMap { status in
            let group = topics.filter { $0.status == status }
            return group.isEmpty ? nil : (status, group)
        }
    }

    var body: some View {
        let _ = aliasRevision
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                ModelMessage()
                generalCard
                segments
                if topics.isEmpty { emptyState }
                else {
                    VStack(alignment: .leading, spacing: 0) {
                        if done {
                            let groups = doneGroups(topics)
                            ForEach(Array(groups.enumerated()), id: \.element.status) { index, group in
                                Text(group.status.label).themeFont(13, .semibold).foregroundStyle(Theme.muted)
                                    .padding(.horizontal, 18).padding(.top, 14)
                                ForEach(group.topics) { topic in topicRow(topic) }
                                if index < groups.count - 1 { ShellDivider().padding(.leading, 74) }
                            }
                        } else { ForEach(topics) { topic in topicRow(topic) } }
                    }.background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
                }
            }.padding(16)
        }
        .background(Theme.bg.ignoresSafeArea()).navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(name).themeFont(17, .semibold).lineLimit(1)
                    PresenceLine(lastSeen: summary?.workspace.lastSeen)
                }
            }
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
    }

    private var generalCard: some View {
        NavigationLink { ChatRoomView(workspaceId: workspaceId).toolbar(.visible, for: .navigationBar) } label: {
            HStack(spacing: 12) {
                ShellAvatar(name: name, size: 50)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 5) {
                        Text("General").themeFont(17, .semibold)
                        Image(systemName: "bubble.right").themeFont(12).foregroundStyle(Theme.muted).accessibilityHidden(true)
                    }
                    Text("Talk to \(name)").themeFont(15).foregroundStyle(Theme.muted)
                }
                Spacer(minLength: 4)
                ShellBadge(count: summary?.general.unread ?? 0)
                ShellChevron()
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("general-\(workspaceId)")
    }

    private var segments: some View {
        HStack(spacing: 0) {
            segment("Open", selected: !done) { done = false }
            segment("Done", selected: done) { done = true }
        }.padding(4).background(Theme.surface2, in: RoundedRectangle(cornerRadius: 12))
    }
    private func segment(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).themeFont(15, .semibold).foregroundStyle(selected ? Theme.brand : Theme.muted)
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(selected ? Theme.surface3 : Theme.surface2, in: RoundedRectangle(cornerRadius: 10))
        }.buttonStyle(PressStyle()).accessibilityIdentifier("segment-\(title.lowercased())")
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    @ViewBuilder private func topicRow(_ topic: TopicSummary) -> some View {
        if !topic.isStarting, let ticket = topic.id.ticket {
            NavigationLink(value: ChatRoute.ticket(workspace: workspaceId, ticket: ticket)) { topicLabel(topic) }
                .buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("ticket-\(workspaceId)|\(ticket)")
        } else { topicLabel(topic) }
    }

    private func topicLabel(_ topic: TopicSummary) -> some View {
        HStack(spacing: 18) {
            Image(systemName: topic.isStarting ? "circle" : symbol(topic.status))
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
        if topic.isStarting { return "Starting topic…" }
        let day = ShellTime.day(topic.lastAt)
        return topic.status.label + (done && !day.isEmpty ? " · " + day : "")
    }
    private func symbol(_ status: TopicStatus) -> String {
        switch status { case .working, .waitingOnYou: "clock"; case .done: "checkmark"; case .stopped: "stop.fill"; case .didntWork: "exclamationmark.triangle" }
    }
    private func color(_ status: TopicStatus) -> Color {
        switch status { case .waitingOnYou: Theme.warn; case .stopped: Theme.muted; case .didntWork: Theme.danger; default: Theme.brand }
    }
    private var emptyState: some View {
        VStack(spacing: 14) {
            OrbitMark().frame(width: 46, height: 46)
            Text("Nothing here yet.").themeFont(20, .semibold)
            Text("Start a topic when you have something to work on.").themeFont(15).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(.vertical, 54)
    }
}
