import SwiftUI

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
    @State private var requestingPermission = false
    private var statusText: String {
        switch model.connection {
        case .ok: "Connected · " + (model.lastUpdatedText?.lowercased() ?? "last updated just now")
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
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Your computer").themeFont(17)
                                    if model.connection != .ok { Text(statusText).themeFont(13).foregroundStyle(statusColor) }
                                }
                                Spacer()
                                Circle().fill(statusColor).frame(width: 8, height: 8)
                            }.padding(16).accessibilityLabel(statusText)
                            ShellDivider()
                            ForEach(model.workspaceSummaries) { summary in
                                NavigationLink { WorkspaceSettingsView(workspaceId: summary.id) } label: {
                                    HStack(spacing: 12) {
                                        WorkspaceBadge(name: WorkspaceAlias.name(for: summary.workspace), icon: summary.workspace.icon, color: summary.workspace.color, size: 42)
                                        VStack(alignment: .leading, spacing: 6) {
                                            Text(WorkspaceAlias.name(for: summary.workspace)).themeFont(17)
                                            Text("Your computer · Connected").themeFont(13).foregroundStyle(Theme.muted)
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
                            Toggle(isOn: Binding(get: { model.notificationsEnabled }, set: { enabled in
                                model.notificationsEnabled = enabled
                                if enabled {
                                    requestingPermission = true
                                    Task { model.notificationsEnabled = await PushPermission.request(); requestingPermission = false }
                                }
                            })) {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Notifications").themeFont(17)
                                    Text("Questions and finished work").themeFont(13).foregroundStyle(Theme.muted)
                                }
                            }.tint(Theme.brand).padding(16).disabled(requestingPermission)
                            ShellDivider()
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
                            Text("Only finished (Done) chats with no new message move to Archived. Chats waiting for you, in Review, and Your helper never do. A new message brings a chat back.")
                                .themeFont(13).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                                .padding(.horizontal, 16).padding(.top, 10).padding(.bottom, 16)
                        }
                    }
                    Text("Tickets started from your phone send answers here, even when Send questions to my phone is off.")
                        .themeFont(13).foregroundStyle(Theme.muted)
                    Button { confirmSignOut = true } label: {
                        Text("Sign out").themeFont(17).foregroundStyle(Theme.danger).padding(.horizontal, 12)
                            .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).accessibilityLabel("Sign out")
                    if confirmSignOut {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Disconnect this phone? You will need a new invitation to connect again.").themeFont(13)
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
                        Text("orch for iOS · \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"))")
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
    private var tomorrow: Date {
        let calendar = Calendar.current
        let next = calendar.date(byAdding: .day, value: 1, to: Date()) ?? Date()
        return calendar.date(bySettingHour: 8, minute: 0, second: 0, of: next) ?? next
    }
    private var selectedMute: String {
        guard let workspace, workspace.isMuted() else { return "Off" }
        if workspace.mutedUntil == "forever" { return "Always" }
        if let date = ShellTime.date(workspace.mutedUntil), abs(date.timeIntervalSince(tomorrow)) < 60 { return "Until tomorrow" }
        return "For 1 hour"
    }
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
                VStack(alignment: .leading, spacing: 10) {
                    Eyebrow(text: "MUTE")
                    VStack(spacing: 0) {
                        ForEach(["Off", "For 1 hour", "Until tomorrow", "Always"], id: \.self) { option in
                            Button { changeMute(option) } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(option)
                                        if option == "Until tomorrow" { Text("08:00").themeFont(13).foregroundStyle(Theme.muted) }
                                    }
                                    Spacer()
                                    if selectedMute == option { Image(systemName: "checkmark").foregroundStyle(Theme.brand) }
                                }.themeFont(17).padding(16).frame(minHeight: 48).contentShape(Rectangle())
                            }.buttonStyle(PressStyle()).accessibilityAddTraits(selectedMute == option ? .isSelected : []).accessibilityIdentifier("mute-\(option)")
                            if option != "Always" { ShellDivider().padding(.leading, 16) }
                        }
                    }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).disabled(busy)
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
    private func changeMute(_ option: String) {
        busy = true
        let mute: Mute
        switch option {
        case "Always": mute = .forever
        case "For 1 hour": mute = .until(Date().addingTimeInterval(3600))
        case "Until tomorrow": mute = .until(tomorrow)
        default: mute = .off
        }
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
    @State private var saving = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Defaults for all chats").themeFont(13).foregroundStyle(Theme.muted)
                ModelMessage()
                VStack(alignment: .leading, spacing: 10) {
                    Eyebrow(text: "VOICE REPLIES")
                    Picker("Voice replies", selection: Binding(get: { model.settings.speak }, set: { update(SettingsPatch(speak: $0)) })) {
                        ForEach(PhoneSettings.Speak.allCases, id: \.self) { option in
                            Text(option == .auto ? "Auto (long answers)" : option == .always ? "Always" : "Never")
                                .tag(option).accessibilityIdentifier("speak-\(option.rawValue)")
                        }
                    }.pickerStyle(.menu).tint(Theme.text).themeFont(17).padding(16)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                        .disabled(saving).accessibilityIdentifier("voice-replies-menu")
                }
                VStack(alignment: .leading, spacing: 10) {
                    Eyebrow(text: "LISTENING & SPEECH")
                    Toggle("I speak Swiss German", isOn: Binding(get: { model.settings.swissGerman }, set: { update(SettingsPatch(swissGerman: $0)) }))
                        .themeFont(17).tint(Theme.brand).padding(16).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)).disabled(saving)
                }
                VStack(alignment: .leading, spacing: 10) {
                    Eyebrow(text: "VOICE BUDGET")
                    Picker("Monthly limit", selection: Binding(get: { model.settings.ttsCapUsd }, set: { update(SettingsPatch(ttsCapUsd: $0)) })) {
                        ForEach([0, 5, 10, 20, 50], id: \.self) { amount in
                            Text("$\(amount)").tag(Double(amount))
                        }
                    }.pickerStyle(.menu).tint(Theme.text).themeFont(17).padding(16)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                        .disabled(saving).accessibilityIdentifier("voice-limit-menu")
                    Text(String(format: "Used this month $%.2f · left $%.2f", model.settings.ttsUsedUsdMonth, model.settings.ttsLeftUsd))
                        .themeFont(13).foregroundStyle(Theme.muted)
                }
            }.padding(16)
        }.background(Theme.bg.ignoresSafeArea()).foregroundStyle(Theme.text)
            .navigationTitle("Voice").navigationBarTitleDisplayMode(.inline)

    }
    private func update(_ patch: SettingsPatch) {
        saving = true
        Task { await model.updateSettings(patch); saving = false }
    }
}
