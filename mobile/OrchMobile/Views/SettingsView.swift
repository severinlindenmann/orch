import SwiftUI
import UserNotifications

/// What the Notifications row shows, from the system permission.
enum NotificationAccess: Equatable {
    case allowed, denied, notAsked
    static func from(_ status: UNAuthorizationStatus) -> NotificationAccess {
        switch status {
        case .denied: .denied
        case .notDetermined: .notAsked
        default: .allowed
        }
    }
}

enum SignOutWording {
    static let base = "Disconnect this phone? You will need a new invitation to connect again."
    /// Items not yet stored by the relay are lost on sign-out.
    static func text(for items: [OutboxItem]) -> String {
        let n = notSent(items)
        return text(messages: n.messages, answers: n.answers)
    }
    static func text(messages: Int, answers: Int) -> String {
        guard let what = counted(messages: messages, answers: answers) else { return base }
        let verb = messages + answers == 1 ? "is" : "are"
        return base + " " + what + " \(verb) still waiting to be sent and will be lost."
    }
    /// Messages and answers the relay has not stored yet (waiting or refused).
    static func notSent(_ items: [OutboxItem]) -> (messages: Int, answers: Int) {
        let waiting = items.filter { $0.sentMessageId == nil }
        return (waiting.filter { $0.kind == .send }.count, waiting.filter { $0.kind == .answer }.count)
    }
    /// The relay refused this phone (401): the line after the sign-out names what was waiting and is now gone.
    static func revoked(notSent n: (messages: Int, answers: Int)) -> String {
        let signedOut = RelayError.unauthorized.localizedDescription
        guard let what = counted(messages: n.messages, answers: n.answers) else { return signedOut }
        let verb = n.messages + n.answers == 1 ? "was" : "were"
        return signedOut + " " + what + " waiting on this phone \(verb) not sent."
    }
    private static func counted(messages: Int, answers: Int) -> String? {
        var parts: [String] = []
        if messages > 0 { parts.append("\(messages) \(messages == 1 ? "message" : "messages")") }
        if answers > 0 { parts.append("\(answers) \(answers == 1 ? "answer" : "answers")") }
        return parts.isEmpty ? nil : parts.joined(separator: " and ")
    }
}

enum WorkspaceAlias {
    static func name(for ws: Workspace) -> String {
        (UserDefaults.standard.dictionary(forKey: "workspaceAlias") as? [String: String])?[ws.id] ?? ws.displayName
    }
    static func set(_ name: String?, for id: String) {
        var aliases = UserDefaults.standard.dictionary(forKey: "workspaceAlias") as? [String: String] ?? [:]
        let clean = name?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        aliases[id] = clean.isEmpty ? nil : clean
        guard aliases != (UserDefaults.standard.dictionary(forKey: "workspaceAlias") as? [String: String] ?? [:]) else { return }
        UserDefaults.standard.set(aliases, forKey: "workspaceAlias")
        UserDefaults.standard.set(UserDefaults.standard.integer(forKey: "workspaceAliasRevision") &+ 1, forKey: "workspaceAliasRevision")
    }
}

struct SettingsView: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var addWorkspace = false
    @State private var confirmSignOut = false
    @State private var signingOut = false
    private var statusText: String {
        switch model.connection {
        case .ok: "Connected"
        case .unreachable: "Can't reach the server"
        case .checking: "Checking…"
        }
    }
    private var statusColor: Color {
        switch model.connection { case .ok: Theme.online; case .unreachable: Theme.danger; case .checking: Theme.muted }
    }
    var body: some View {
        let _ = aliasRevision
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    section("Notifications") { MuteAllSettings() }
                    ModelMessage()
                    section("WORKSPACES") {
                        VStack(spacing: 0) {
                            HStack {
                                Text("Connection").themeFont(17)
                                Spacer()
                                Circle().fill(statusColor).frame(width: 8, height: 8).accessibilityHidden(true)
                                Text(statusText).themeFont(15).foregroundStyle(model.connection == .unreachable ? Theme.danger : Theme.muted)
                            }.padding(16).frame(minHeight: 52).accessibilityElement(children: .ignore)
                                .accessibilityLabel("Connection, \(statusText)").accessibilityIdentifier("settings-connection")
                            ShellDivider()
                            ForEach(model.workspaceSummaries) { summary in
                                NavigationLink { WorkspaceSettingsView(workspaceId: summary.id) } label: {
                                    HStack(spacing: 12) {
                                        WorkspaceBadge(name: WorkspaceAlias.name(for: summary.workspace), icon: summary.workspace.icon, color: summary.workspace.color, size: 42)
                                        VStack(alignment: .leading, spacing: 6) {
                                            Text(WorkspaceAlias.name(for: summary.workspace)).themeFont(17)
                                            TimelineView(.everyMinute) { context in Text(model.status(lastSeen: summary.workspace.lastSeen, now: context.date).text(now: context.date)) }.themeFont(13).foregroundStyle(Theme.muted)
                                        }
                                        Spacer(); ShellChevron()
                                    }.padding(16).frame(minHeight: 64).contentShape(Rectangle())
                                }.buttonStyle(PressStyle()).accessibilityIdentifier("settings-ws-\(summary.id)")
                                ShellDivider().padding(.leading, 16)
                            }
                            Button { addWorkspace = true } label: {
                                HStack { Text("Add workspace"); Spacer(); Image(systemName: "plus") }.themeFont(17)
                                    .foregroundStyle(Theme.brand).padding(.horizontal, 16).frame(minHeight: 52).contentShape(Rectangle())
                            }.buttonStyle(PressStyle()).accessibilityIdentifier("add-workspace")
                        }
                    }
                    section("PREFERENCES") {
                        VStack(spacing: 0) {
                            NavigationLink { VoiceSettingsView() } label: {
                                HStack(spacing: 12) {
                                    Image(systemName: "mic").themeFont(20)
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text("Voice").themeFont(17)
                                        Text("Voice and languages").themeFont(13).foregroundStyle(Theme.muted)
                                    }
                                    Spacer(); ShellChevron()
                                }.padding(16).frame(minHeight: 52).contentShape(Rectangle())
                            }.buttonStyle(PressStyle()).accessibilityIdentifier("voice-settings")
                        }
                    }
                    section("CHATS") {
                        VStack(alignment: .leading, spacing: 0) {
                            Toggle("Archive old chats automatically", isOn: Binding(get: { model.archive.autoDays > 0 },
                                set: { model.setAutoArchive(days: $0 ? 7 : 0) }))
                                .themeFont(17).tint(Theme.brand).frame(minHeight: 44).padding(16).accessibilityIdentifier("auto-archive")
                            if model.archive.autoDays > 0 {
                                ShellDivider().padding(.leading, 16)
                                NavigationLink { AutoArchiveDaysView() } label: {
                                    HStack { Text("After"); Spacer(); Text("\(model.archive.autoDays) days").foregroundStyle(Theme.muted); ShellChevron() }
                                        .themeFont(17).padding(16).frame(minHeight: 52).contentShape(Rectangle())
                                }.buttonStyle(PressStyle()).accessibilityIdentifier("auto-archive-days")
                                    .accessibilityLabel("Archive after").accessibilityValue("\(model.archive.autoDays) days")
                            }
                            Text("Finished chats move to Archived after a while. A new message brings them back.")
                                .themeFont(13).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                                .padding(.horizontal, 16).padding(.top, 10).padding(.bottom, 16)
                        }
                    }
                    if let fingerprint = PhoneKey.fingerprint() {
                        section("THIS PHONE") {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Fingerprint").themeFont(17)
                                Text(fingerprint).font(.system(size: 15, design: .monospaced)).foregroundStyle(Theme.text)
                                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                                Text("Your workspaces show this when they accept this phone. Check that it matches.")
                                    .themeFont(13).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                                // One id on the combined element only: an id on the inner Text too shows up twice (duplicate-id UI test).
                                .accessibilityElement(children: .combine).accessibilityIdentifier("phone-fingerprint")
                        }
                    }
                    Button { confirmSignOut = true } label: {
                        Text("Sign out").themeFont(17).foregroundStyle(Theme.danger).padding(.horizontal, 12)
                            .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).accessibilityLabel("Sign out")
                    if confirmSignOut {
                        VStack(alignment: .leading, spacing: 12) {
                            Text(SignOutWording.text(for: model.outbox.items)).themeFont(13).fixedSize(horizontal: false, vertical: true)
                            Button {
                                signingOut = true
                                Task { await model.signOut(); signingOut = false }
                            } label: {
                                HStack { if signingOut { ProgressView() }; Text(signingOut ? "Signing out…" : "Sign out of this phone") }
                            }.buttonStyle(WideButtonStyle(color: Theme.danger)).accessibilityIdentifier("signout-confirm")
                            Button("Cancel") { confirmSignOut = false }.buttonStyle(WideButtonStyle(color: Theme.muted))
                        }.orchCard().disabled(signingOut).id("signout-card")
                    }
                    HStack(spacing: 8) {
                        OrbitMark().frame(width: 24, height: 24)
                        Text("orch for iOS \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")")
                            .themeFont(11).foregroundStyle(Theme.muted)
                    }.frame(maxWidth: .infinity)
                }.padding(16)
            }.onChange(of: confirmSignOut) { _, shown in
                guard shown else { return }
                if reduceMotion { proxy.scrollTo("signout-card", anchor: .bottom) }
                else { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("signout-card", anchor: .bottom) } }
            }
        }.background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
            .navigationTitle("Settings").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar)
            .sheet(isPresented: $addWorkspace) { AddWorkspaceView().presentationDetents([.medium, .large]) }
    }
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: title)
            content().background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
        }
    }
}

struct WorkspaceSettingsView: View {
    let workspaceId: String
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var removing = false
    @State private var busy = false
    private var workspace: Workspace? { model.workspaceSummaries.first { $0.id == workspaceId }?.workspace }
    private var displayName: String { workspace.map { WorkspaceAlias.name(for: $0) } ?? "Workspace" }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                ModelMessage()
                VStack(alignment: .leading, spacing: 10) {
                    Eyebrow(text: "NAME")
                    TextField("Workspace name", text: $name).themeFont(17).padding(16)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).accessibilityLabel("Workspace name")
                        .submitLabel(.done).onSubmit { WorkspaceAlias.set(name, for: workspaceId) }
                    Text("Only changes how it looks on this phone.").themeFont(13).foregroundStyle(Theme.muted)
                }
                TimelineView(.everyMinute) { context in
                    let value = MuteRules.notificationsValue(workspace?.mutedUntil, now: context.date)
                    Menu {
                        if value != "On" { Button("Unmute", systemImage: "bell") { changeMute(.off) } }
                        MuteChoices { changeMute($0) }
                    } label: {
                        HStack {
                            Text("Notifications").foregroundStyle(Theme.text)
                            Spacer()
                            Text(value).foregroundStyle(Theme.muted).lineLimit(1).minimumScaleFactor(0.8)
                            Image(systemName: "chevron.up.chevron.down").themeFont(13).foregroundStyle(Theme.muted).accessibilityHidden(true)
                        }.themeFont(17).padding(16).frame(minHeight: 52).contentShape(Rectangle())
                    }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).disabled(busy)
                        .accessibilityLabel("Notifications").accessibilityValue(value).accessibilityIdentifier("workspace-notifications")
                }
                Button("Remove from this phone") { removing = true }.buttonStyle(WideButtonStyle(color: Theme.danger, bordered: true)).disabled(busy).accessibilityIdentifier("remove-workspace")
            }.padding(16)
        }.background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
            .navigationTitle(displayName).navigationBarTitleDisplayMode(.inline)
            .onAppear { name = workspace.map { WorkspaceAlias.name(for: $0) } ?? "" }
            .onDisappear { if workspace != nil { WorkspaceAlias.set(name, for: workspaceId) } }
            .confirmationDialog("Remove \(displayName) from this phone?", isPresented: $removing, titleVisibility: .visible) {
                Button("Remove", role: .destructive) {
                    busy = true
                    Task {
                        await model.removeWorkspace(workspaceId); busy = false
                        if workspace == nil { WorkspaceAlias.set(nil, for: workspaceId); dismiss() }
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: { Text("Its chats disappear from this phone. You can add it again with a new invitation.") }
    }
    private func changeMute(_ mute: Mute) {
        busy = true
        Task { await model.setMute(workspaceId, mute); busy = false }
    }
}

struct AutoArchiveDaysView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                ForEach(ArchiveStore.dayChoices, id: \.self) { days in
                    Button { model.setAutoArchive(days: days) } label: {
                        HStack { Text("\(days) days"); Spacer(); if model.archive.autoDays == days { Image(systemName: "checkmark").foregroundStyle(Theme.brand).accessibilityHidden(true) } }
                            .themeFont(17).padding(16).frame(minHeight: 48).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).accessibilityAddTraits(model.archive.autoDays == days ? .isSelected : [])
                        .accessibilityIdentifier("auto-archive-\(days)")
                    if days != ArchiveStore.dayChoices.last { ShellDivider().padding(.leading, 16) }
                }
            }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).padding(16)
        }.background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
            .navigationTitle("Archive after").navigationBarTitleDisplayMode(.inline)
    }
}

struct VoiceSettingsView: View {
    @Environment(AppModel.self) private var model
    @AppStorage(NewTopicRules.autoMicKey) private var autoMic = false
    @State private var saving = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                ModelMessage()
                VStack(alignment: .leading, spacing: 10) {
                    VStack(spacing: 0) {
                        row("Voice replies") {
                            Picker("Voice replies", selection: Binding(get: { model.settings.speak }, set: { update(SettingsPatch(speak: $0)) })) {
                                ForEach(PhoneSettings.Speak.allCases, id: \.self) { option in
                                    Text(option == .auto ? "Auto (long answers)" : option == .always ? "Always" : "Never")
                                        .tag(option).accessibilityIdentifier("speak-\(option.rawValue)")
                                }
                            }.accessibilityIdentifier("voice-replies-menu")
                        }
                        ShellDivider().padding(.leading, 16)
                        Toggle("I speak Swiss German", isOn: Binding(get: { model.settings.swissGerman }, set: { update(SettingsPatch(swissGerman: $0)) }))
                            .themeFont(17).tint(Theme.brand).padding(16).frame(minHeight: 52)
                        ShellDivider().padding(.leading, 16)
                        VStack(alignment: .leading, spacing: 4) {
                            Toggle("Start recording right away", isOn: $autoMic).themeFont(17).tint(Theme.brand)
                                .accessibilityIdentifier("auto-mic")
                            Text("New topic opens with the microphone on").themeFont(13).foregroundStyle(Theme.muted)
                        }.padding(16).frame(minHeight: 52)
                    }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).disabled(saving)
                    Text("Defaults for all chats").themeFont(13).foregroundStyle(Theme.muted).padding(.horizontal, 16)
                }
                VStack(alignment: .leading, spacing: 10) {
                    Eyebrow(text: "VOICE BUDGET")
                    row("Monthly limit (USD)") {
                        Picker("Monthly limit (USD)", selection: Binding(get: { model.settings.ttsCapUsd }, set: { update(SettingsPatch(ttsCapUsd: $0)) })) {
                            ForEach([0, 5, 10, 20, 50], id: \.self) { amount in
                                Text("$\(amount)").tag(Double(amount)).accessibilityIdentifier("limit-\(amount)")
                            }
                        }.accessibilityIdentifier("voice-limit-menu")
                    }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).disabled(saving)
                    Text(String(format: "Used this month US$%.2f · left US$%.2f", model.settings.ttsUsedUsdMonth, model.settings.ttsLeftUsd))
                        .themeFont(13).foregroundStyle(Theme.muted).padding(.horizontal, 16)
                }
            }.padding(16)
        }.background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
            .navigationTitle("Voice").navigationBarTitleDisplayMode(.inline)

    }
    /// A Settings row: label left, value and menu right.
    private func row<Control: View>(_ label: String, @ViewBuilder control: () -> Control) -> some View {
        HStack {
            Text(label).themeFont(17)
            Spacer(minLength: 8)
            control().pickerStyle(.menu).tint(Theme.muted).labelsHidden()
        }.padding(.horizontal, 16).frame(minHeight: 52).accessibilityElement(children: .combine)
    }
    private func update(_ patch: SettingsPatch) {
        saving = true
        Task { await model.updateSettings(patch); saving = false }
    }
}
