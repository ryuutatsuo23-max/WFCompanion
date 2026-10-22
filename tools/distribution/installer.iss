#ifndef Payload
  #error Payload must point to the built application directory
#endif
#ifndef Version
  #error Version is required
#endif
#ifndef Output
  #error Output directory is required
#endif
#ifndef Branding
  #define Branding "assets"
#endif
[Setup]
AppId=WFCompanion
AppName=WFCompanion
AppVersion={#Version}
#ifdef PublicBuild
InfoBeforeFile=public_notices\RUNTIME.md
#endif
DefaultDirName={localappdata}\Programs\WFCompanion
DefaultGroupName=WFCompanion
DisableProgramGroupPage=yes
AllowNoIcons=no
PrivilegesRequired=lowest
OutputDir={#Output}
#ifdef PatchName
OutputBaseFilename={#PatchName}
#else
OutputBaseFilename=WFCompanion-Setup
#endif
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern dark includetitlebar
WizardBackImageFile={#Branding}\wizard-background.png
WizardImageFile={#Branding}\wizard-sidebar.png
WizardSmallImageFile={#Branding}\forever.png
SetupIconFile={#Branding}\forever.ico
DisableWelcomePage=no
MinVersion=10.0.19041
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=Local\WFCompanion
CloseApplications=no
UninstallDisplayIcon={app}\WFCompanion.exe
[Types]
Name: companion; Description: "Companion only"
Name: recommended; Description: "Companion and Storage addon"
Name: custom; Description: "Choose components"; Flags: iscustom
[Components]
Name: companion; Description: "WFCompanion (includes runtime)"; Types: companion recommended custom; Flags: fixed
Name: storage; Description: "Forever Storage - bags and bank (includes required Core)"; Types: recommended
Name: probe; Description: "Stress Probe - diagnostics (optional)"
Name: display; Description: "Display Test - experimental combat display (optional)"
[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut for WFCompanion"; GroupDescription: "Shortcuts:"
[Icons]
Name: "{userprograms}\WFCompanion\Uninstall WFCompanion"; Filename: "{uninstallexe}"; IconFilename: "{app}\WFCompanion.exe"
Name: "{app}\Uninstall WFCompanion"; Filename: "{uninstallexe}"; IconFilename: "{app}\WFCompanion.exe"
Name: "{userprograms}\WFCompanion\WFCompanion"; Filename: "{app}\WFCompanion.exe"; WorkingDir: "{app}"; IconFilename: "{app}\WFCompanion.exe"; Comment: "WoW Forever companion - characters, inventory and wishlists"; AppUserModelID: "WFCompanion.Desktop"
Name: "{userdesktop}\WFCompanion"; Filename: "{app}\WFCompanion.exe"; WorkingDir: "{app}"; IconFilename: "{app}\WFCompanion.exe"; Comment: "Open the WoW Forever companion"; AppUserModelID: "WFCompanion.Desktop"; Tasks: desktopicon
[Run]
Filename: "{app}\WFCompanion.exe"; Description: "Open WFCompanion"; Flags: postinstall nowait skipifsilent
[Code]
var
  ClientPage: TInputDirWizardPage;
  FullBanner: TBitmapImage;
  BannerPanel: TPanel;
  DeleteCompanionData: Boolean;

function InitializeUninstall: Boolean;
begin
  Result := True;
  DeleteCompanionData := SuppressibleMsgBox('Also delete your saved WFCompanion data on this PC?' + #13#10 + #13#10 +
    'Yes permanently removes companion characters, plans, settings, imported records and local backups.' + #13#10 +
    'No keeps them for a later reinstall (recommended).' + #13#10 + #13#10 +
    'WoW addons and their SavedVariables are never removed.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
end;

function UnlinkedTree(const Folder: String): Boolean;
var Entry: TFindRec;
begin
  Result := True;
  if FindFirst(Folder, Entry) then begin
    try
      if (Entry.Attributes and $400) <> 0 then Result := False;
    finally FindClose(Entry); end;
  end;
  if not Result then Exit;
  if FindFirst(AddBackslash(Folder) + '*', Entry) then begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
          if (Entry.Attributes and $400) <> 0 then Result := False
          else if (Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            Result := UnlinkedTree(AddBackslash(Folder) + Entry.Name);
          if not Result then Exit;
        end;
      until not FindNext(Entry);
    finally FindClose(Entry); end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var DataRoot: String; ParentInfo: TFindRec; SafeParent: Boolean;
begin
  if (CurUninstallStep = usPostUninstall) and DeleteCompanionData then begin
    DataRoot := ExpandConstant('{localappdata}\WoWForever\Companion');
    SafeParent := True;
    if FindFirst(ExpandConstant('{localappdata}\WoWForever'), ParentInfo) then begin
      try SafeParent := (ParentInfo.Attributes and $400) = 0;
      finally FindClose(ParentInfo); end;
    end;
    if DirExists(DataRoot) then begin
      if SafeParent and UnlinkedTree(DataRoot) then begin
        if not DelTree(DataRoot, True, True, True) then
          SuppressibleMsgBox('Some companion data could not be removed. Remaining files are in: ' + DataRoot, mbInformation, MB_OK, IDOK);
      end else
        SuppressibleMsgBox('Saved data was kept because its folder contains a linked directory or file. No linked data was deleted.', mbInformation, MB_OK, IDOK);
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { A windowed parent keeps the artwork above the notebook on welcome/finish.
    Hide the entire parent on content pages, so no bitmap can bleed through. }
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WizardBitmapImage2.Visible := False;
  BannerPanel.Visible := (CurPageID = wpWelcome) or (CurPageID = wpFinished);
  if BannerPanel.Visible then BannerPanel.BringToFront;
  WizardForm.Refresh;
end;

function HasAddons: Boolean;
begin
#ifdef PatchName
  Result := False;
#else
  Result := WizardIsComponentSelected('storage') or WizardIsComponentSelected('probe') or WizardIsComponentSelected('display');
#endif
end;

procedure InitializeWizard;
begin
  { Keep all artwork inside the inset decorative border at each Windows DPI. }
  WizardForm.WizardBitmapImage.Left := WizardForm.WizardBitmapImage.Left + ScaleX(10);
  WizardForm.WizardBitmapImage.Top := WizardForm.WizardBitmapImage.Top + ScaleY(10);
  WizardForm.WizardBitmapImage.Width := WizardForm.WizardBitmapImage.Width - ScaleX(16);
  WizardForm.WizardBitmapImage.Height := WizardForm.WizardBitmapImage.Height - ScaleY(20);
  WizardForm.WizardBitmapImage2.SetBounds(WizardForm.WizardBitmapImage.Left,
    WizardForm.WizardBitmapImage.Top, WizardForm.WizardBitmapImage.Width, WizardForm.WizardBitmapImage.Height);
  BannerPanel := TPanel.Create(WizardForm);
  BannerPanel.Parent := WizardForm;
  BannerPanel.Visible := False;
  BannerPanel.BevelOuter := bvNone;
  BannerPanel.SetBounds(ScaleX(10), ScaleY(10), WizardForm.WizardBitmapImage.Width,
    WizardForm.ClientHeight - ScaleY(20));
  FullBanner := TBitmapImage.Create(WizardForm);
  FullBanner.Parent := BannerPanel;
  FullBanner.Bitmap.Assign(WizardForm.WizardBitmapImage.Bitmap);
  FullBanner.Stretch := True;
  FullBanner.SetBounds(0, 0, BannerPanel.Width, BannerPanel.Height);
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WizardBitmapImage2.Visible := False;
  FullBanner.Visible := True;
  WizardForm.WizardSmallBitmapImage.Left := WizardForm.WizardSmallBitmapImage.Left - ScaleX(10);
  WizardForm.WizardSmallBitmapImage.Top := WizardForm.WizardSmallBitmapImage.Top + ScaleY(10);
  WizardForm.WizardSmallBitmapImage.Width := WizardForm.WizardSmallBitmapImage.Width - ScaleX(10);
  WizardForm.WizardSmallBitmapImage.Height := WizardForm.WizardSmallBitmapImage.Height - ScaleY(10);
  ClientPage := CreateInputDirPage(wpSelectComponents, 'WoW Forever folder',
    'Choose the client for the selected addons',
    'Select _forever_ or _classic_beta_ containing Wow.exe. Close WoW first. Existing addon code is backed up; game saves and other addons are preserved.', False, '');
  ClientPage.Add('Client folder:');
  ClientPage.Values[0] := GetPreviousData('ClientFolder', ExpandConstant('{autopf32}\World of Warcraft\_forever_'));
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ClientPage.ID) and not HasAddons;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Name: String;
begin
  Result := True;
  if (CurPageID = ClientPage.ID) and HasAddons then begin
    Name := ExtractFileName(RemoveBackslashUnlessRoot(ClientPage.Values[0]));
    Result := ((Name = '_forever_') or (Name = '_classic_beta_')) and FileExists(AddBackslash(ClientPage.Values[0]) + 'Wow.exe');
    if not Result then MsgBox('Choose a Forever client folder containing Wow.exe.', mbError, MB_OK);
  end;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'ClientFolder', ClientPage.Values[0]);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Selected: String; Code: Integer;
begin
  if (CurStep = ssPostInstall) and HasAddons then begin
    Selected := '';
    if WizardIsComponentSelected('storage') then Selected := 'WFStorage,WFCore';
    if WizardIsComponentSelected('probe') then Selected := Selected + ',WFStressProbe';
    if WizardIsComponentSelected('display') then Selected := Selected + ',WFDisplayTest';
    if Copy(Selected, 1, 1) = ',' then Delete(Selected, 1, 1);
    if not Exec(ExpandConstant('{app}\WFCompanion.exe'), '--install-addons "' + ClientPage.Values[0] + '" --addons "' + Selected + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      MsgBox('The companion was installed, but addon installation did not finish. Close WoW and check folder permissions, then rerun setup with those addons selected. Details are in LocalAppData\WoWForever\Companion\addon-install-error.txt.', mbError, MB_OK);
  end;
end;

#ifdef PatchValidation
#include PatchValidation
#endif
