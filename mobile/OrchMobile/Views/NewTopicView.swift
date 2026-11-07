import SwiftUI

struct NewTopicScreen: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    var workspaceId: String?
    var asSheet = false
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var selectedId: String?
    @State private var text = ""
    @State private var sending = false
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
                // PLACEHOLDER composer: replaced by Composer.swift (lane M2)
                HStack(alignment: .bottom, spacing: 6) {
                    Button {} label: { Image(systemName: "plus").frame(width: 44, height: 44) }
                        .disabled(true).accessibilityLabel("Add attachment")
                    TextField("Message…", text: $text, axis: .vertical)
                        .themeFont(17).lineLimit(1...6).padding(.horizontal, 14).padding(.vertical, 12)
                        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 24))
                        .overlay(RoundedRectangle(cornerRadius: 24).stroke(Theme.borderStrong, lineWidth: 1.5))
                        .focused($focused).accessibilityIdentifier("topic-field").disabled(sending)
                    Button { send() } label: {
                        Group { if sending { ProgressView().tint(Theme.onBrand) } else { Image(systemName: "arrow.up").themeFont(20, .semibold) } }
                            .foregroundStyle(Theme.onBrand).frame(width: 44, height: 44)
                            .background(Theme.brand, in: Circle()).opacity(canSend ? 1 : 0.5)
                    }.buttonStyle(PressStyle()).disabled(!canSend).accessibilityLabel("Start topic").accessibilityIdentifier("topic-start")
                }
                Text("Start something with \(name).").themeFont(13).foregroundStyle(Theme.muted)
                if selected == nil { Text("Add a workspace first.").themeFont(15).foregroundStyle(Theme.muted) }
                ModelMessage()
            }.padding(16).padding(.top, asSheet ? 16 : 0)
        }
        .background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
        .navigationTitle(asSheet ? "" : "New topic").navigationBarTitleDisplayMode(.inline)
        .presentationBackground(Theme.surface).presentationDragIndicator(.visible)
        .interactiveDismissDisabled(sending)
        .task {
            if selectedId == nil { selectedId = selected?.id }
            if !UserDefaults.standard.bool(forKey: "autoMic") { focused = true }
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
    private var canSend: Bool { selected != nil && !sending && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    private func send() {
        guard canSend, let ws = selected?.id else { return }
        sending = true; focused = false
        let priorSendTick = model.sendTick
        let priorErrorTick = model.errorTick
        let priorQueuedIds = Set(model.chatData.outbox.map(\.id))
        Task {
            await model.startTopic(workspaceId: ws, text: text.trimmingCharacters(in: .whitespacesAndNewlines))
            sending = false
            // A sheet can already sit above this workspace route. Require evidence
            // of a sent/queued text as well, so a failed send keeps its draft.
            let opened: Bool
            switch model.path.last {
            case .workspace(let id): opened = id == ws
            case .ticket(let id, _): opened = id == ws
            default: opened = false
            }
            let queued = model.chatData.outbox.contains { $0.workspace == ws && !priorQueuedIds.contains($0.id) }
            let accepted = model.sendTick > priorSendTick || queued
            if opened && accepted && model.errorTick == priorErrorTick {
                text = ""
                if asSheet { dismiss() }
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
