import SwiftUI

struct NewTopicScreen: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    var workspaceId: String?
    var asSheet = false
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var selectedId: String?
    @State private var picking = false
    @FocusState private var focused: Bool
    private var selected: WorkspaceSummary? {
        model.workspaceSummaries.first { $0.id == (selectedId ?? workspaceId) } ?? model.workspaceSummaries.first
    }
    private var name: String { selected.map { WorkspaceAlias.name(for: $0.workspace) } ?? "a workspace" }

    var body: some View {
        let _ = aliasRevision
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if asSheet {
                    HStack { Text("New topic").themeFont(20, .semibold); Spacer(); ShellCloseButton { dismiss() } }
                }
                HStack(spacing: 8) {
                    Text("To:").themeFont(15).foregroundStyle(Theme.muted)
                    if model.workspaceSummaries.count > 1 {
                        Button { focused = false; picking = true } label: { recipientPill }
                            .buttonStyle(PressStyle()).accessibilityLabel("Choose workspace, \(name)").accessibilityIdentifier("workspace-picker")
                    } else { recipientPill }
                }
                Composer(target: selected.map { .newTopic(workspace: $0.id) }, placeholder: "Message…", autoFocus: true,
                         reply: .constant(nil), onSent: { opened() }, fieldId: "topic-field", sendId: "topic-start")
                Text("Start something with \(name).").themeFont(13).foregroundStyle(Theme.muted)
                if selected == nil { Text("Add a workspace first.").themeFont(15).foregroundStyle(Theme.muted) }
                ModelMessage()
            }.padding(16).padding(.top, asSheet ? 16 : 0)
        }
        .background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
        .navigationTitle(asSheet ? "" : "New topic").navigationBarTitleDisplayMode(.inline)
        .presentationBackground(Theme.surface).presentationDragIndicator(.visible)
        .task {
            if selectedId == nil { selectedId = selected?.id }
        }
        .sheet(isPresented: $picking) {
            ShellWorkspacePicker(selectedId: selected?.id) { id in selectedId = id }
        }
    }
    private var recipientPill: some View {
        HStack(spacing: 6) {
            Text(name).themeFont(15, .semibold)
            if model.workspaceSummaries.count > 1 { Image(systemName: "chevron.down").themeFont(10).accessibilityHidden(true) }
        }.padding(.horizontal, 16).frame(minHeight: 44).background(Theme.surface3, in: Capsule()).foregroundStyle(Theme.text)
    }
    /// The first message is queued or sent: leave the sheet and show the workspace (the topic reads "Starting topic…").
    /// When the workspace acks within a few seconds the new topic opens by itself.
    private func opened() {
        guard let ws = selected?.id else { return }
        // The message was just queued or sent, so its "starting" conversation exists; follow it until the workspace's ack names the ticket.
        let starting = model.workspaceSummaries.first { $0.id == ws }?.topics.first { $0.isStarting }?.id
        model.path = [.workspace(ws)]
        if asSheet { dismiss() }
        guard let starting else { return }
        Task { @MainActor in
            for _ in 0..<10 {
                try? await Task.sleep(for: .milliseconds(700))
                await model.reloadMessages(); await model.refreshUpdates()
                guard model.path == [.workspace(ws)] else { return }   // the person went elsewhere
                var ticket: String? = nil
                if case .topic(_, let t) = model.resolve(starting) { ticket = t }
                else if case .starting(_, let key) = starting, let id = model.messages.first(where: { ($0.clientId ?? $0.message.body.clientId) == key })?.id {
                    ticket = model.ack(for: id)?.ticket   // the ack may arrive as a work update before it shows as a message
                }
                if let ticket { model.path = [.workspace(ws), .ticket(workspace: ws, ticket: ticket)]; return }
            }
        }
    }
}

private struct ShellWorkspacePicker: View {
    let selectedId: String?
    let select: (String) -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    var body: some View {
        NavigationStack {
            List {
                ForEach(model.workspaceSummaries.filter { query.isEmpty || WorkspaceAlias.name(for: $0.workspace).localizedCaseInsensitiveContains(query) }) { summary in
                    Button {
                        select(summary.id); dismiss()
                    } label: {
                        HStack(spacing: 12) {
                            ShellAvatar(name: WorkspaceAlias.name(for: summary.workspace), online: summary.presence.isOnline)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(WorkspaceAlias.name(for: summary.workspace)).themeFont(17, .semibold)
                                PresenceLine(presence: summary.presence)
                            }
                            Spacer()
                            if selectedId == summary.id { Image(systemName: "checkmark").foregroundStyle(Theme.brand) }
                        }.frame(minHeight: 44).foregroundStyle(Theme.text)
                    }.accessibilityIdentifier("pick-\(summary.id)").listRowBackground(Theme.surface)
                        .accessibilityAddTraits(selectedId == summary.id ? .isSelected : [])
                }
            }.scrollContentBackground(.hidden).background(Theme.bg)
                .searchable(text: $query, prompt: "Search workspaces").navigationTitle("Choose workspace")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }
}
