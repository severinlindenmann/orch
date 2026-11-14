import SwiftUI
import UIKit

/// New topic, built for busy hands (driving, carrying): pick the workspace tile, one huge microphone, Photo / Camera, and
/// "Type instead" for the old text field. With the "Start recording right away" setting the screen opens recording.
struct NewTopicScreen: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    @AppStorage(NewTopicRules.lastWorkspaceKey) private var lastUsed = ""
    var workspaceId: String?
    var asSheet = false
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private enum Mode { case home, typing, recording }
    @State private var mode = Mode.home
    @State private var selectedId: String?
    @State private var picking = false
    @State private var morePicking = false
    @State private var media: MediaPicker.Start?
    @State private var error: String?
    @State private var success = 0
    @State private var autoStarted = false
    private var ids: [String] { model.workspaceSummaries.map(\.id) }
    private var selected: WorkspaceSummary? {
        model.workspaceSummaries.first { $0.id == selectedId } ?? model.workspaceSummaries.first
    }
    private var name: String { selected.map { WorkspaceAlias.name(for: $0.workspace) } ?? "a workspace" }

    var body: some View {
        let _ = aliasRevision
        Group {
            switch mode {
            case .home: home
            case .typing: typing
            case .recording:
                if let selected {
                    NewTopicVoiceView(workspace: selected, name: name, onCancel: { mode = .home },
                                      onFailed: { error = $0; mode = .home }, onSent: { remember(); opened() })
                }
            }
        }
        .background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
        .navigationTitle(asSheet || mode != .home ? "" : "New topic").navigationBarTitleDisplayMode(.inline)
        .presentationBackground(Theme.surface).presentationDragIndicator(.visible)
        .sensoryFeedback(.success, trigger: success)
        .task {
            if selectedId == nil {
                selectedId = NewTopicRules.initialSelection(ids: ids, lastUsed: lastUsed.isEmpty ? nil : lastUsed, opener: workspaceId)
            }
            if !autoStarted, NewTopicRules.opensRecording(autoMic: UserDefaults.standard.bool(forKey: NewTopicRules.autoMicKey), hasWorkspace: selected != nil) {
                autoStarted = true; await startRecording()
            }
        }
        .sheet(isPresented: $picking) { ShellWorkspacePicker(selectedId: selected?.id) { id in choose(id) } }
        .sheet(isPresented: $morePicking) { WorkspaceGridPicker(selectedId: selected?.id) { id in choose(id) } }
        .sheet(item: $media) { start in
            MediaPicker(start: start) { selection in Task { await sendMedia(selection) } }.tint(Theme.brand)
        }
    }

    // MARK: Home

    private var home: some View {
        ScrollView {
            VStack(spacing: 20) {
                header
                if ids.count > 1 { tileRow } else if selected != nil { Text("To \(name)").themeFont(17, .semibold).frame(maxWidth: .infinity, alignment: .leading) }
                if selected == nil { Text("Add a workspace first.").themeFont(15).foregroundStyle(Theme.muted) }
                else {
                    Button { Task { await startRecording() } } label: {
                        Image(systemName: "mic.fill").font(.system(size: 64)).foregroundStyle(Theme.onBrand)
                            .frame(width: 168, height: 168).background(Theme.brand, in: Circle())
                    }.buttonStyle(PressStyle()).padding(.top, 8)
                        .accessibilityLabel("Talk to \(name)").accessibilityIdentifier("nt-mic")
                    VStack(spacing: 4) {
                        Text("Tap and talk").themeFont(22, .semibold)
                        Text("to \(name)").themeFont(15).foregroundStyle(Theme.muted)
                    }.accessibilityHidden(true)
                    if let error { Text(error).themeFont(14).foregroundStyle(Theme.danger).multilineTextAlignment(.center) }
                    HStack(spacing: 12) {
                        bigButton("Photo", "photo", "nt-photo") { media = .library }
                        if UIImagePickerController.isSourceTypeAvailable(.camera) { bigButton("Camera", "camera", "nt-camera") { media = .camera } }
                    }
                    Button { mode = .typing } label: {
                        Text("Type instead").themeFont(15, .semibold).foregroundStyle(Theme.muted)
                            .frame(minWidth: 120, minHeight: 44).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).accessibilityIdentifier("nt-type")
                }
            }.padding(16).padding(.top, asSheet ? 8 : 0)
        }
    }
    private var header: some View {
        HStack {
            Text("New topic").themeFont(22, .semibold).accessibilityAddTraits(.isHeader)
            Spacer()
            if asSheet { ShellCloseButton { dismiss() } }
        }
    }
    private func bigButton(_ title: String, _ icon: String, _ id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) { Image(systemName: icon).themeFont(22); Text(title).themeFont(17, .semibold) }
                .frame(maxWidth: .infinity, minHeight: 76).background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                .foregroundStyle(Theme.text)
        }.buttonStyle(PressStyle()).accessibilityIdentifier(id)
    }
    private var tileRow: some View {
        let shown = NewTopicRules.tiles(ids: ids, preferred: lastUsed.isEmpty ? workspaceId : lastUsed, selected: selected?.id)
        return VStack(alignment: .leading, spacing: 8) {
            Text("To").themeFont(13, .semibold).foregroundStyle(Theme.muted)
            HStack(spacing: 8) {
                ForEach(shown, id: \.self) { id in
                    if let summary = model.workspaceSummaries.first(where: { $0.id == id }) { tile(summary) }
                }
                if NewTopicRules.hasMore(count: ids.count) {
                    Button { morePicking = true } label: {
                        VStack(spacing: 6) {
                            Image(systemName: "ellipsis").themeFont(20).frame(width: 40, height: 40)
                            Text("More").themeFont(13).lineLimit(2)
                        }.frame(maxWidth: .infinity, minHeight: 88).background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                            .foregroundStyle(Theme.text)
                    }.buttonStyle(PressStyle()).accessibilityIdentifier("nt-more")
                }
            }
        }
    }
    private func tile(_ summary: WorkspaceSummary) -> some View {
        let on = summary.id == selected?.id, label = WorkspaceAlias.name(for: summary.workspace)
        return Button { choose(summary.id) } label: {
            VStack(spacing: 6) {
                WorkspaceBadge(name: label, icon: summary.workspace.icon, color: summary.workspace.color, size: 40)
                Text(label).themeFont(13, .semibold).lineLimit(2).multilineTextAlignment(.center)
            }.padding(.horizontal, 4).frame(maxWidth: .infinity, minHeight: 88)
                .background(on ? Theme.brand.opacity(0.14) : Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(on ? Theme.brand : .clear, lineWidth: 2))
                .foregroundStyle(Theme.text)
        }.buttonStyle(PressStyle()).accessibilityIdentifier("nt-ws-\(summary.id)")
            .accessibilityLabel(label).accessibilityAddTraits(on ? .isSelected : [])
    }
    private func choose(_ id: String) { selectedId = id }

    // MARK: Type instead (today's screen)

    private var typing: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                HStack(spacing: 8) {
                    Text("To:").themeFont(15).foregroundStyle(Theme.muted)
                    if model.workspaceSummaries.count > 1 {
                        Button { picking = true } label: { recipientPill }
                            .buttonStyle(PressStyle()).accessibilityLabel("Choose workspace, \(name)").accessibilityIdentifier("workspace-picker")
                    } else { recipientPill }
                }
                Composer(target: selected.map { .newTopic(workspace: $0.id) }, placeholder: "Message…", autoFocus: true,
                         reply: .constant(nil), onSent: { remember(); opened() }, fieldId: "topic-field", sendId: "topic-start")
                Text("Start something with \(name).").themeFont(13).foregroundStyle(Theme.muted)
                if selected == nil { Text("Add a workspace first.").themeFont(15).foregroundStyle(Theme.muted) }
                ModelMessage()
            }.padding(16).padding(.top, asSheet ? 8 : 0)
        }
    }
    private var recipientPill: some View {
        HStack(spacing: 6) {
            Text(name).themeFont(15, .semibold)
            if model.workspaceSummaries.count > 1 { Image(systemName: "chevron.down").themeFont(10).accessibilityHidden(true) }
        }.padding(.horizontal, 16).frame(minHeight: 44).background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).foregroundStyle(Theme.text)
    }

    // MARK: Recording (NewTopicVoice.swift)

    private func startRecording() async {
        guard selected != nil, mode != .recording else { return }
        error = nil; mode = .recording
    }
    /// A photo or camera shot from the big buttons: the topic starts with that picture.
    private func sendMedia(_ selection: MediaSelection) async {
        defer { selection.cleanUp() }
        guard let selected else { return }
        let draft: MessageDraft
        switch selection {
        case .files(let files, let caption): draft = MessageDraft(text: caption, files: files, replyTo: nil)
        case .location(let place): draft = MessageDraft(location: place, replyTo: nil)
        }
        do {
            try await model.send(draft, to: .newTopic(workspace: selected.id))
            success += 1; remember()
            UIAccessibility.post(notification: .announcement, argument: "Sent to \(name)")
            opened()
        } catch { self.error = error.localizedDescription }
    }
    private func remember() { if let id = selected?.id { lastUsed = id } }
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


extension MediaPicker.Start: Identifiable { var id: Int { self == .library ? 0 : 1 } }

/// "Send to": every workspace as a big tile, one tap picks and closes.
private struct WorkspaceGridPicker: View {
    let selectedId: String?
    let select: (String) -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Button { dismiss() } label: {
                    Image(systemName: "chevron.left").themeFont(17, .semibold).frame(width: 44, height: 44).background(Theme.surface2, in: Circle())
                }.buttonStyle(PressStyle()).accessibilityLabel("Back").accessibilityIdentifier("nt-pick-back")
                Text("Send to").themeFont(22, .semibold).accessibilityAddTraits(.isHeader)
                Spacer()
            }
            ScrollView {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                    ForEach(model.workspaceSummaries) { summary in
                        let on = summary.id == selectedId, label = WorkspaceAlias.name(for: summary.workspace)
                        Button { select(summary.id); dismiss() } label: {
                            VStack(spacing: 8) {
                                WorkspaceBadge(name: label, icon: summary.workspace.icon, color: summary.workspace.color, size: 48)
                                Text(label).themeFont(15, .semibold).lineLimit(2).multilineTextAlignment(.center)
                            }.padding(8).frame(maxWidth: .infinity, minHeight: 120)
                                .background(on ? Theme.brand.opacity(0.14) : Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(on ? Theme.brand : .clear, lineWidth: 2))
                                .foregroundStyle(Theme.text)
                        }.buttonStyle(PressStyle()).accessibilityIdentifier("nt-pick-\(summary.id)")
                            .accessibilityAddTraits(on ? .isSelected : [])
                    }
                }
            }
        }.padding(16).background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
            .presentationDetents([.large]).presentationBackground(Theme.surface)
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
