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
                        Button { picking = true } label: { recipientPill }
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
        .sheet(isPresented: $picking, onDismiss: {
            // The picker took the keyboard with it: give the field focus back once it is gone.
            if !UserDefaults.standard.bool(forKey: "autoMic") { focused = true }
        }) {
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
        model.path = [.workspace(ws)]
        if asSheet { dismiss() }
        Task { @MainActor in
            for _ in 0..<15 {
                // Newest text this phone sent to the workspace; the workspace's ack names the ticket it started.
                let mine = model.messages.filter { $0.fromPhone && $0.workspaceId == ws }.max { $0.message.createdAt < $1.message.createdAt }
                if let mine, let ticket = mine.message.ticket ?? model.ack(for: mine.id)?.ticket,
                   model.path == [.workspace(ws)] {
                    model.path = [.workspace(ws), .ticket(workspace: ws, ticket: ticket)]; return
                }
                try? await Task.sleep(for: .milliseconds(700))
                await model.reloadMessages(); await model.refreshUpdates()
                guard model.path == [.workspace(ws)] else { return }   // the person went elsewhere
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
                            WorkspaceBadge(name: WorkspaceAlias.name(for: summary.workspace), icon: summary.workspace.icon, color: summary.workspace.color, lastSeen: .some(summary.workspace.lastSeen))
                            VStack(alignment: .leading, spacing: 4) {
                                Text(WorkspaceAlias.name(for: summary.workspace)).themeFont(17, .semibold)
                                PresenceLine(lastSeen: summary.workspace.lastSeen)
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
